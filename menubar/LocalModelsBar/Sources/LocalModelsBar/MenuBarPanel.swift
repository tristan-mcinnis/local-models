// SHARED KIT, DO NOT EDIT. Source: design-system/kit/MenuBarPanel.swift.
// Copy from design-system (`make sync-kit` there); `make check-consumers`
// fails when a consumer's copy differs.
//
// The menu-bar panel plumbing every house menu-bar app shares, following the
// "Menu bar panel" component in design-system/DESIGN.md: the action row, the
// section label and note lines, and the NSPanel controller that hangs a 300 px
// glass panel under the status item, routes the keyboard and closes on focus
// loss. An app owns its model, its panel view and its controller subclass, in
// app-local files.

import AppKit
import SwiftUI

/// One selectable row in the panel.
struct PanelAction: Identifiable {
    let id: String
    let glyph: String
    let title: String
    /// The chord drawn as key caps on the right. Empty draws none.
    var chord: String = ""
    var isEnabled: Bool = true
    /// A rarer action, drawn at reduced ink in the second group.
    var isQuiet: Bool = false
    var run: () -> Void = {}
}

/// One 36 px action row: a glyph, a `label` title, and outlined key caps.
/// `glyphWidth` is the glyph's column; a panel whose other rows carry an icon
/// tile passes `House.Control.tile` so the titles line up.
struct PanelRow: View {
    let action: PanelAction
    let isSelected: Bool
    let onHover: () -> Void
    let onTap: () -> Void
    var glyphWidth: CGFloat = 16

    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: House.Spacing.sm) {
                Image(systemName: action.glyph)
                    .font(.system(size: House.TypeToken.Size.bodySmall))
                    .foregroundStyle(House.ColorToken.textSecondary)
                    .frame(width: glyphWidth)
                Text(action.title)
                    .font(House.TypeToken.label)
                    .foregroundStyle(House.ColorToken.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: House.Spacing.xs)
                if !action.chord.isEmpty {
                    KeyCaps(chord: action.chord)
                }
            }
            .padding(.horizontal, House.Spacing.sm)
            .frame(height: House.Control.railRow)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(background)
            .contentShape(Rectangle())
            .opacity(opacity)
        }
        .buttonStyle(.plain)
        .disabled(!action.isEnabled)
        .onHover { if $0 { onHover() } }
        .accessibilityAddTraits(isSelected ? [.isButton, .isSelected] : .isButton)
    }

    /// Disabled reads as disabled; the rarer group is quieter than the verbs
    /// but still fully legible.
    private var opacity: Double {
        if !action.isEnabled { return 0.45 }
        return action.isQuiet ? 0.75 : 1
    }

    @ViewBuilder
    private var background: some View {
        let shape = RoundedRectangle(cornerRadius: House.Radius.row, style: .continuous)
        if isSelected && action.isEnabled {
            shape
                .fill(House.ColorToken.selectionFill)
                .overlay(shape.strokeBorder(House.ColorToken.selectionRing, lineWidth: House.hairline))
                .houseShadow(House.Shadow.selection, dark: scheme == .dark)
        } else {
            shape.fill(Color.clear)
        }
    }
}

/// An uppercase `section` label inside the panel ("TODAY", "SUBSCRIPTIONS").
struct PanelSectionLabel: View {
    let text: String
    var topPadding: CGFloat = House.Spacing.xs

    var body: some View {
        Text(text.uppercased())
            .font(House.TypeToken.section)
            .tracking(House.TypeToken.Tracking.section)
            .foregroundStyle(House.ColorToken.textTertiary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, House.Spacing.sm)
            .padding(.top, topPadding)
            .padding(.bottom, 2)
    }
}

/// A dim explanatory line inside the panel: "No hits", "3 more", or the reason
/// a section could not be read.
struct PanelNote: View {
    let text: String
    var danger = false
    var verticalPadding: CGFloat = House.Spacing.xxs

    var body: some View {
        Text(text)
            .font(House.TypeToken.meta)
            .foregroundStyle(danger ? House.ColorToken.danger : House.ColorToken.textTertiary)
            .lineLimit(2)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, House.Spacing.sm)
            .padding(.vertical, verticalPadding)
    }
}

// MARK: - Panel window

/// A borderless panel that can take key focus, so arrows, Return and Escape
/// drive it without a pointer, and inline fields can be typed into.
final class KeyablePanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

/// The parts of a key-down the panel reads. `NSEvent` is not Sendable, so the
/// monitor copies these out before it hops onto the main actor.
struct KeyPress: Sendable {
    let keyCode: UInt16
    let flags: NSEvent.ModifierFlags
    let characters: String?

    init(_ event: NSEvent) {
        keyCode = event.keyCode
        flags = event.modifierFlags
        characters = event.charactersIgnoringModifiers
    }
}

/// What the controller needs from an app's panel model.
@MainActor
protocol MenuPanelModeling: AnyObject {
    /// The controller sets this to close the panel.
    var onClose: () -> Void { get set }
    func moveSelection(by delta: Int)
    func runSelection()
    /// Escape. A model with nothing to back out of calls `onClose()`.
    func escape()
}

/// Owns the menu-bar panel window: shows it under the status item, routes the
/// keyboard, and closes it on focus loss. An app subclasses it to reset its
/// model on open (`panelWillShow`), release it on close (`panelDidClose`), and
/// add its own keys (`handle`, falling back to `super`).
@MainActor
class MenuPanelController<Content: View, Model: MenuPanelModeling> {
    let model: Model

    private(set) var panel: KeyablePanel?
    private(set) var hosting: NSHostingView<Content>?
    private let width: CGFloat
    private let makeRootView: () -> Content
    private var keyMonitor: Any?
    private var resignObserver: NSObjectProtocol?

    var isVisible: Bool { panel?.isVisible ?? false }

    init(model: Model, width: CGFloat, rootView: @escaping () -> Content) {
        self.model = model
        self.width = width
        self.makeRootView = rootView
        model.onClose = { [weak self] in self?.close() }
    }

    func toggle(relativeTo button: NSStatusBarButton?) {
        if isVisible { close() } else { show(relativeTo: button) }
    }

    func show(relativeTo button: NSStatusBarButton?) {
        let panel = self.panel ?? makePanel()
        self.panel = panel
        panelWillShow()

        panel.setContentSize(panel.contentView?.fittingSize ?? NSSize(width: width + 32, height: 320))
        if let origin = anchorFrame(for: button, size: panel.frame.size) {
            panel.setFrameOrigin(origin)
        } else {
            panel.center()
        }
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startKeyMonitor()
        observeResign(panel)
    }

    func close() {
        stopKeyMonitor()
        if let resignObserver {
            NotificationCenter.default.removeObserver(resignObserver)
            self.resignObserver = nil
        }
        panelDidClose()
        panel?.orderOut(nil)
    }

    /// Runs once the window exists, before it is sized and shown: reset the
    /// model for a fresh open.
    func panelWillShow() {}

    /// Runs once the key monitor and focus observer are gone, before the
    /// window hides.
    func panelDidClose() {}

    /// Arrows and Return drive the rows; Escape goes to the model. True when
    /// the key was handled and must not reach the focused view.
    func handle(_ key: KeyPress) -> Bool {
        switch key.keyCode {
        case 125: // down
            model.moveSelection(by: 1)
            return true
        case 126: // up
            model.moveSelection(by: -1)
            return true
        case 36, 76: // return, enter
            model.runSelection()
            return true
        case 53: // esc
            model.escape()
            return true
        default:
            return false
        }
    }

    private func makePanel() -> KeyablePanel {
        let hosting = NSHostingView(rootView: makeRootView())
        hosting.setFrameSize(hosting.fittingSize)
        self.hosting = hosting

        let panel = KeyablePanel(
            contentRect: NSRect(origin: .zero, size: hosting.fittingSize),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.contentView = hosting
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .statusBar
        panel.isReleasedWhenClosed = false
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.appearance = AppearancePreference.current.nsAppearance
        return panel
    }

    /// Anchor under the status item, clamped to the screen.
    func anchorFrame(for button: NSStatusBarButton?, size: NSSize) -> NSPoint? {
        guard let button, let window = button.window else { return nil }
        let inScreen = window.convertToScreen(button.convert(button.bounds, to: nil))
        let screen = NSScreen.screens.first(where: { $0.frame.intersects(inScreen) }) ?? NSScreen.main
        var x = inScreen.midX - size.width / 2
        let y = inScreen.minY - size.height
        if let visible = screen?.visibleFrame {
            x = min(max(x, visible.minX), visible.maxX - size.width)
        }
        return NSPoint(x: x, y: y)
    }

    // MARK: Keyboard

    private func startKeyMonitor() {
        guard keyMonitor == nil else { return }
        // Only the key's Sendable parts cross into the main actor; the event
        // itself stays in the monitor, which returns it or swallows it.
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self, self.isVisible else { return event }
            let key = KeyPress(event)
            let consumed = MainActor.assumeIsolated { self.handle(key) }
            return consumed ? nil : event
        }
    }

    private func stopKeyMonitor() {
        if let keyMonitor { NSEvent.removeMonitor(keyMonitor) }
        keyMonitor = nil
    }

    private func observeResign(_ panel: NSPanel) {
        guard resignObserver == nil else { return }
        resignObserver = NotificationCenter.default.addObserver(
            forName: NSWindow.didResignKeyNotification, object: panel, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.close() }
        }
    }
}
