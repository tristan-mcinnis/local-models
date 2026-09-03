import AppKit
import ServiceManagement
import SwiftUI

/// Local Models has one settings pane, so the shared Slate shell is used at
/// its smallest: a 220 px rail with a single row, a 60 px pane header, cards on
/// the window ground, and a footer well. The shell is the same one Cotype and
/// Memory use (memory-menubar/Sources/MemoryBar/SettingsView.swift); a second
/// pane would slot into the rail without changing anything else.
struct SettingsView: View {
    @ObservedObject var model: PanelModel

    @AppStorage(AppearancePreference.key) private var appearance = AppearancePreference.dark.rawValue
    @AppStorage(PanelModel.pollIntervalKey) private var pollInterval = 60.0
    @State private var launchAtLogin = LoginItem.isEnabled
    @State private var loginItemNote: String?

    /// The intervals worth offering: often enough to see a model go warm,
    /// rare enough to be free. Each one is an HTTP call every N seconds.
    private static let intervals: [(value: Double, title: String)] = [
        (30, "30 s"), (60, "1 min"), (300, "5 min"),
    ]

    var body: some View {
        HStack(spacing: 0) {
            rail
            pane
        }
        .background(House.ColorToken.surface)
        .frame(minWidth: 720, minHeight: 460)
    }

    // MARK: - Rail

    private var rail: some View {
        VStack(alignment: .leading, spacing: House.Spacing.sm) {
            AppMark(symbol: "cpu", name: "Local Models", caption: "Settings")
                .padding(.horizontal, House.Spacing.xs)
                .padding(.top, House.Spacing.xxl)
            RailRow(symbol: "gearshape", title: "General", isSelected: true) {}
            Spacer(minLength: 0)
        }
        .padding(.horizontal, House.Spacing.sm)
        .frame(width: House.Layout.settingsRail)
        .frame(maxHeight: .infinity)
        .background(House.ColorToken.surfaceSunken)
        .overlay(alignment: .trailing) {
            House.ColorToken.divider.frame(width: House.hairline)
        }
    }

    // MARK: - Pane

    private var pane: some View {
        VStack(spacing: 0) {
            PaneHeader(
                title: "General",
                purpose: "How Local Models looks, when it starts, and how often it asks the daemon."
            )
            // The window hides its title bar, so the pane starts under the
            // traffic lights; this is the clearance for them.
            .padding(.top, House.Spacing.lg)
            ScrollView {
                VStack(alignment: .leading, spacing: House.Spacing.md) {
                    appearanceCard
                    daemonCard
                }
                .padding(House.Spacing.lg)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            FooterWell {
                FooterStatus(text: model.headline, tint: footerTint)
            } trailing: {
                KeyHint(title: "Close", chord: "⌘ W")
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var footerTint: Color {
        switch model.health {
        case .running: return House.ColorToken.success
        case .down: return House.ColorToken.danger
        case .unknown: return House.ColorToken.textTertiary
        }
    }

    // MARK: - Cards

    private var appearanceCard: some View {
        SlateCard(section: "Appearance") {
            SlateRow(title: "Theme", detail: "Dark is the house default; light is first-class.") {
                SlateSegmented(
                    options: AppearancePreference.allCases.map { ($0.rawValue, $0.title) },
                    selection: Binding(
                        get: { appearance },
                        set: { newValue in
                            appearance = newValue
                            AppearancePreference.applyCurrent()
                        }
                    )
                )
                .frame(width: 230)
            }
            SlateDivider()
            SlateRow(
                title: "Launch at login",
                detail: loginItemNote ?? "Local Models has no Dock icon; it lives in the menu bar."
            ) {
                InkSwitch(isOn: Binding(
                    get: { launchAtLogin },
                    set: { wanted in
                        loginItemNote = LoginItem.set(wanted)
                        launchAtLogin = LoginItem.isEnabled
                    }
                ))
            }
        }
    }

    private var daemonCard: some View {
        SlateCard(
            section: "Daemon",
            footnote: "Local Models drives the local-models launchd job; it does not own it. With the panel open it always polls every 5 s."
        ) {
            SlateRow(
                title: "Poll interval",
                detail: "How often Local Models asks the daemon with the panel closed."
            ) {
                SlateSegmented(
                    options: Self.intervals.map { ($0.value, $0.title) },
                    selection: $pollInterval
                )
                .frame(width: 230)
            }
            SlateDivider()
            SlateBlock {
                SlateInfoRow(title: "Job", value: DaemonAgent.label, monospaced: true)
                SlateInfoRow(title: "Plist", value: DaemonAgent.plistPath, monospaced: true)
                SlateInfoRow(
                    title: "Log",
                    value: NSHomeDirectory() + "/Library/Logs/local-models.log",
                    monospaced: true
                )
                SlateInfoRow(
                    title: "Registry",
                    value: NSHomeDirectory() + "/Models/models.json",
                    monospaced: true
                )
            }
        }
        .onChange(of: pollInterval) { _, _ in model.schedulePoll() }
    }
}

/// The login item, through `SMAppService`. The app is a menu-bar accessory, so
/// this registers the whole bundle rather than a helper.
enum LoginItem {
    static var isEnabled: Bool {
        SMAppService.mainApp.status == .enabled
    }

    /// Returns a note when the change could not be made, so the pane can say
    /// what happened instead of quietly showing the wrong switch.
    static func set(_ enabled: Bool) -> String? {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
            return nil
        } catch {
            return "could not change the login item: \(error.localizedDescription)"
        }
    }
}
