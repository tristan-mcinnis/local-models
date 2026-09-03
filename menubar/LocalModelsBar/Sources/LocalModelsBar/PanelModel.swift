import AppKit
import Foundation

/// One model as the daemon reports it on `GET /v1/models`.
struct ModelRow: Decodable, Identifiable, Equatable {
    let id: String
    let backend: String
    let capabilities: [String]
    let warm: Bool
    let backendAvailable: Bool

    enum CodingKeys: String, CodingKey {
        case id, backend, capabilities, warm
        case backendAvailable = "backend_available"
    }

    /// The row's secondary line: what the model can do. The backend is left
    /// out on purpose — with the warm chip beside it there is not room for
    /// both at 300 px, and the capabilities are what a reader is choosing on.
    var detail: String {
        let caps = capabilities.joined(separator: " · ")
        return caps.isEmpty ? backend : caps
    }
}

struct ModelList: Decodable {
    let models: [ModelRow]
}

/// One selectable row in the panel that is not a model: a verb.
struct PanelAction: Identifiable {
    let id: String
    let glyph: String
    let title: String
    /// The chord drawn as key caps on the right. Empty draws none.
    var chord: String = ""
    var isEnabled: Bool = true
    var run: () -> Void = {}
}

/// The launchd agent that is the daemon. Local Models drives a job it does not
/// own, so both verbs go through `launchctl` rather than through the HTTP API:
/// the daemon has no stop route, and it is `KeepAlive`, so killing the process
/// only makes launchd start it again.
enum DaemonAgent {
    static let label = "com.local-models.server"

    static var plistPath: String {
        NSHomeDirectory() + "/Library/LaunchAgents/\(label).plist"
    }

    static var isInstalled: Bool {
        FileManager.default.fileExists(atPath: plistPath)
    }

    private static var target: String { "gui/\(getuid())/\(label)" }

    /// Bootstrap the job if it was booted out, then kick it. The bootstrap is
    /// a no-op (and prints to its own pipe) when the job is already loaded.
    static func start() {
        run(["bootstrap", "gui/\(getuid())", plistPath])
        run(["kickstart", "-k", target])
    }

    /// Boot the job out. `KeepAlive` means nothing softer than this stops it.
    static func stop() {
        run(["bootout", target])
    }

    private static func run(_ arguments: [String]) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        process.arguments = arguments
        process.standardOutput = Pipe()
        process.standardError = Pipe()
        try? process.run()
        process.waitUntilExit()
    }
}

/// The panel's live state and every action behind it.
///
/// Local Models owns no model and no daemon. The rows are the registry the
/// daemon reports, and the two verbs on a row are the daemon's own `warm` and
/// `unload` routes. Nothing here blocks the main thread: every call is async
/// and the panel keeps drawing the last snapshot until a new one lands.
@MainActor
final class PanelModel: ObservableObject {

    // MARK: Published state

    @Published private(set) var models: [ModelRow] = []
    @Published private(set) var daemonUp = false
    /// True until the first answer lands, and again on a manual refresh. The
    /// dot is dim while this is raised, so "not running" is never guessed.
    @Published private(set) var isRefreshing = true
    /// The model id a warm or unload call is running against.
    @Published private(set) var busy: String?
    @Published var selection: Int = 0

    // MARK: Collaborators

    private let base = URL(string: "http://127.0.0.1:8078")!
    private var pollTimer: Timer?
    private let defaults: UserDefaults

    /// Raised while the panel is on screen, so polling speeds up.
    var isPanelOpen = false { didSet { schedulePoll() } }

    var onOpenSettings: () -> Void = {}
    var onQuit: () -> Void = {}
    var onClose: () -> Void = {}
    /// Fired whenever the daemon state changes, so the status item can repaint.
    var onStateChange: () -> Void = {}

    static let pollIntervalKey = "pollIntervalSeconds"
    /// How often the panel asks the daemon while it is open.
    static let openPollInterval: TimeInterval = 5

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    // MARK: - Derived facts

    var warmCount: Int { models.filter(\.warm).count }

    /// The header's status line, beside the dot. Always paired with the word,
    /// never colour alone.
    var headline: String {
        if isRefreshing && models.isEmpty && !daemonUp { return "Checking the daemon…" }
        guard daemonUp else { return "Daemon not running" }
        return "Daemon running · \(warmCount) warm"
    }

    /// The dim second line under the header: where the daemon answers, or why
    /// it cannot be reached.
    var context: String? {
        if daemonUp { return base.host.map { "\($0):\(base.port ?? 8078)" } }
        if isRefreshing { return nil }
        return DaemonAgent.isInstalled
            ? "\(DaemonAgent.label) is not answering"
            : "no launchd job installed (make install-server)"
    }

    enum Health { case running, down, unknown }

    var health: Health {
        if isRefreshing && !daemonUp && models.isEmpty { return .unknown }
        return daemonUp ? .running : .down
    }

    // MARK: - Rows

    /// The second group: the two rarer verbs.
    var moreActions: [PanelAction] {
        [
            PanelAction(id: "refresh", glyph: "arrow.clockwise", title: "Refresh", chord: "⌘R") {
                [weak self] in self?.poll()
            },
            PanelAction(id: "registry", glyph: "folder", title: "Open registry", chord: "") {
                [weak self] in self?.openRegistry()
            },
        ]
    }

    /// Model rows first, then the second group, then the two footer buttons.
    var rowCount: Int { models.count + moreActions.count }
    var footerSelectionBase: Int { rowCount }
    private var selectionCount: Int { rowCount + 2 }

    func moveSelection(by delta: Int) {
        guard selectionCount > 0 else { return }
        let next = (selection + delta + selectionCount) % selectionCount
        selection = next
    }

    /// Return: warm the selected model, run the selected verb, or press the
    /// selected footer button.
    func runSelection() {
        if selection < models.count {
            let model = models[selection]
            guard model.backendAvailable, daemonUp, busy == nil else { return }
            if model.warm { return }
            Task { await warm(model.id) }
            return
        }
        let actionIndex = selection - models.count
        if actionIndex < moreActions.count {
            let action = moreActions[actionIndex]
            guard action.isEnabled else { return }
            action.run()
            return
        }
        if selection == footerSelectionBase { onOpenSettings() } else { onQuit() }
    }

    /// ⌘Return: unload the selected model.
    func unloadSelection() {
        guard selection < models.count else { return }
        let model = models[selection]
        guard model.warm, daemonUp, busy == nil else { return }
        Task { await unload(model.id) }
    }

    func escape() {
        onClose()
    }

    // MARK: - Polling

    func start() {
        schedulePoll()
        poll()
    }

    /// The interval the panel polls at: fast while it is open, the user's
    /// setting while it is closed.
    private var pollInterval: TimeInterval {
        if isPanelOpen { return Self.openPollInterval }
        let stored = defaults.double(forKey: Self.pollIntervalKey)
        return stored > 0 ? stored : 60
    }

    func schedulePoll() {
        pollTimer?.invalidate()
        pollTimer = Timer.scheduledTimer(withTimeInterval: pollInterval, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.poll() }
        }
    }

    func poll() {
        Task { await refresh() }
    }

    func refresh() async {
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            var request = URLRequest(url: base.appendingPathComponent("v1/models"))
            request.timeoutInterval = 3
            let (data, response) = try await URLSession.shared.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
            models = try JSONDecoder().decode(ModelList.self, from: data).models
            daemonUp = true
        } catch {
            models = []
            daemonUp = false
        }
        clampSelection()
        onStateChange()
    }

    private func clampSelection() {
        if selection >= selectionCount { selection = max(0, selectionCount - 1) }
    }

    // MARK: - The daemon's verbs

    func warm(_ id: String) async {
        busy = id
        await post("v1/warm", body: ["model": id], timeout: 180)
        busy = nil
    }

    func unload(_ id: String) async {
        busy = id
        await post("v1/unload", body: ["model": id], timeout: 30)
        busy = nil
    }

    private func post(_ path: String, body: [String: Any], timeout: TimeInterval) async {
        var request = URLRequest(url: base.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        request.timeoutInterval = timeout
        _ = try? await URLSession.shared.data(for: request)
        await refresh()
    }

    // MARK: - The daemon itself

    /// The header switch. Start bootstraps and kicks the launchd job; stop
    /// boots it out, which is the only thing a `KeepAlive` job answers to.
    func setDaemonRunning(_ wanted: Bool) {
        if wanted { DaemonAgent.start() } else { DaemonAgent.stop() }
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            await refresh()
        }
    }

    // MARK: - Registry

    /// Reveal the registry in Finder. User-initiated, so taking the foreground
    /// is what was asked for.
    func openRegistry() {
        let path = NSHomeDirectory() + "/Models/models.json"
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
        onClose()
    }

    // MARK: - Render proof seams

    /// Fixed state for the offscreen proof, so a PNG never depends on whether
    /// this Mac happens to be running the daemon.
    func override(models: [ModelRow], daemonUp: Bool, refreshing: Bool = false) {
        self.models = models
        self.daemonUp = daemonUp
        self.isRefreshing = refreshing
    }
}
