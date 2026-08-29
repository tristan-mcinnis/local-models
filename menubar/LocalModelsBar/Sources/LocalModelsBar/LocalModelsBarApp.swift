import AppKit
import SwiftUI

/// Menu-bar manager for the local-models daemon: see every registered model,
/// which one is warm, load one with a click, unload to free RAM.

struct ModelRow: Decodable, Identifiable {
    let id: String
    let backend: String
    let capabilities: [String]
    let warm: Bool
    let backendAvailable: Bool

    enum CodingKeys: String, CodingKey {
        case id, backend, capabilities, warm
        case backendAvailable = "backend_available"
    }
}

struct ModelList: Decodable {
    let models: [ModelRow]
}

@MainActor
final class DaemonState: ObservableObject {
    @Published var models: [ModelRow] = []
    @Published var daemonUp = false
    @Published var busy: String?

    private let base = URL(string: "http://127.0.0.1:8078")!
    private var timer: Timer?

    init() {
        Task { await refresh() }
        timer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in await self?.refresh() }
        }
    }

    var warmCount: Int { models.filter(\.warm).count }

    func refresh() async {
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
    }

    func warm(_ id: String) async {
        busy = id
        await post("v1/warm", body: ["model": id], timeout: 180)
        busy = nil
    }

    func unload() async {
        await post("v1/unload", body: [:], timeout: 30)
    }

    func startDaemon() {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        process.arguments = ["kickstart", "-k", "gui/\(getuid())/com.local-models.server"]
        try? process.run()
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            await refresh()
        }
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
}

@main
struct LocalModelsBarApp: App {
    @StateObject private var state = DaemonState()

    var body: some Scene {
        MenuBarExtra {
            if state.daemonUp {
                Text(state.warmCount > 0 ? "Daemon: running · \(state.warmCount) warm" : "Daemon: running · nothing warm")
                Divider()
                ForEach(state.models) { model in
                    Button {
                        Task { await state.warm(model.id) }
                    } label: {
                        Label(
                            state.busy == model.id
                                ? "\(model.id) — loading…"
                                : "\(model.id)  (\(model.capabilities.joined(separator: ", ")))",
                            systemImage: model.warm ? "circle.fill" : "circle"
                        )
                    }
                    .disabled(!model.backendAvailable || state.busy != nil)
                }
                Divider()
                Button("Unload active model") { Task { await state.unload() } }
                    .disabled(state.warmCount == 0 || state.busy != nil)
            } else {
                Text("Daemon: not running")
                Button("Start daemon") { state.startDaemon() }
            }
            Button("Refresh") { Task { await state.refresh() } }
            Divider()
            Button("Quit") { NSApp.terminate(nil) }
        } label: {
            Image(systemName: state.daemonUp ? (state.warmCount > 0 ? "cpu.fill" : "cpu") : "cpu")
                .symbolRenderingMode(.hierarchical)
        }
        .menuBarExtraStyle(.menu)
    }
}
