// Copied from memory-menubar/Sources/MemoryBar/HouseUI.swift (2026-09-03),
// which itself came from cotype/Sources/CotypeMenuApp/HouseUI.swift, the first
// Slate menu-bar app. This is the shared component kit — panel glass, icon
// tile, key caps, status dot, ink toggle, cards, rows, footer well, rail,
// segmented control — and Local Models uses it unchanged so the three menu
// bars are one look. Fix a component here and in Cotype and Memory in the same
// session, or the family drifts.
//
// Every value comes from `House` (generated from design-system/tokens.json);
// nothing in this file retypes a token. See design-system/DESIGN.md for the
// rule these components follow.

import SwiftUI
import AppKit

// MARK: - Appearance

/// The user's window appearance choice. Dark is the house default; light is
/// first-class. `system` follows macOS.
enum AppearancePreference: String, CaseIterable, Identifiable {
    case system
    case light
    case dark

    /// UserDefaults key. Registered with `dark` as the default.
    static let key = "appearance"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .system: return "System"
        case .light: return "Light"
        case .dark: return "Dark"
        }
    }

    var nsAppearance: NSAppearance? {
        switch self {
        case .system: return nil
        case .light: return NSAppearance(named: .aqua)
        case .dark: return NSAppearance(named: .darkAqua)
        }
    }

    static var current: AppearancePreference {
        AppearancePreference(rawValue: UserDefaults.standard.string(forKey: key) ?? "") ?? .dark
    }

    /// Apply to the whole app, so every Local Models window (settings, menu-bar panel) resolves the same tokens.
    @MainActor
    static func applyCurrent() {
        NSApp.appearance = current.nsAppearance
    }
}

// MARK: - Shadow plumbing

extension View {
    /// Apply a `House.ShadowSpec` at the given appearance.
    func houseShadow(_ spec: House.ShadowSpec, dark: Bool) -> some View {
        shadow(
            color: Color.black.opacity(spec.opacity(dark: dark)),
            radius: spec.blur / 2,
            x: 0,
            y: spec.y
        )
    }
}

// MARK: - Glass

/// The blur material behind `panelTint` on every floating Local Models panel.
struct HouseBlur: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .hudWindow
        view.blendingMode = .behindWindow
        view.state = .active
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}

/// The shared floating-panel surface: blur material, `panelTint`, `stroke`,
/// `highlightTop`, and the two panel shadows.
struct HouseGlass<Content: View>: View {
    var radius: CGFloat = House.Radius.xl
    @Environment(\.colorScheme) private var scheme
    @ViewBuilder var content: Content

    private var isDark: Bool { scheme == .dark }

    var body: some View {
        content
            .background(
                ZStack {
                    HouseBlur()
                    House.ColorToken.panelTint
                }
            )
            .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(House.ColorToken.stroke, lineWidth: House.hairline)
            )
            .overlay(alignment: .top) {
                House.ColorToken.highlightTop
                    .frame(height: House.hairline)
                    .padding(.horizontal, radius / 2)
            }
            .houseShadow(House.Shadow.panelNear, dark: isDark)
            .houseShadow(House.Shadow.panelFar, dark: isDark)
    }
}

// MARK: - Key caps

/// One outlined key cap: 20 high, `keyCapStroke`, `Radius.xs`, SF (not mono).
struct KeyCap: View {
    let label: String

    var body: some View {
        Text(label)
            .font(House.TypeToken.keyCap)
            .foregroundStyle(House.ColorToken.textSecondary)
            .frame(minWidth: House.Control.keyCap, minHeight: House.Control.keyCap)
            .padding(.horizontal, House.Spacing.xxs)
            .background(
                RoundedRectangle(cornerRadius: House.Radius.xs, style: .continuous)
                    .fill(House.ColorToken.keyCapFill)
            )
            .overlay(
                RoundedRectangle(cornerRadius: House.Radius.xs, style: .continuous)
                    .strokeBorder(House.ColorToken.keyCapStroke, lineWidth: House.hairline)
            )
            .accessibilityLabel(label)
    }
}

/// A chord rendered as one cap per key, the way the mockups draw them.
struct KeyCaps: View {
    let keys: [String]

    init(_ keys: [String]) { self.keys = keys }

    /// The modifier glyphs that always get their own cap.
    private static let modifiers: Set<Character> = ["⌘", "⌥", "⌃", "⇧"]

    /// The cap label for a base key, so "Tab" draws as the ⇥ the mockups show.
    private static func capLabel(_ key: String) -> String {
        switch key.lowercased() {
        case "tab": return "⇥"
        case "escape", "esc": return "esc"
        case "return", "enter": return "↩"
        case "delete", "backspace": return "⌫"
        case "space": return "space"
        default: return key
        }
    }

    /// Split a display chord ("⌥Tab", "⌘,", "⌃.") into its caps: one cap per
    /// leading modifier, then one cap for whatever base key remains.
    init(chord: String) {
        let spaced = chord.split(separator: " ").map(String.init)
        if spaced.count > 1 {
            self.keys = spaced.map(Self.capLabel)
            return
        }
        var caps: [String] = []
        var rest = Substring(chord)
        while let first = rest.first, Self.modifiers.contains(first) {
            caps.append(String(first))
            rest = rest.dropFirst()
        }
        if !rest.isEmpty {
            caps.append(Self.capLabel(String(rest)))
        }
        self.keys = caps.isEmpty ? [chord] : caps
    }

    var body: some View {
        HStack(spacing: House.Spacing.xxs) {
            ForEach(Array(keys.enumerated()), id: \.offset) { _, key in
                KeyCap(label: key)
            }
        }
    }
}

/// A key hint that pairs a word with its caps ("Next word ⇥").
struct KeyHint: View {
    let title: String
    let chord: String

    var body: some View {
        HStack(spacing: House.Spacing.xs) {
            Text(title)
                .font(House.TypeToken.meta)
                .foregroundStyle(House.ColorToken.textSecondary)
                .lineLimit(1)
                .fixedSize()
            KeyCaps(chord: chord)
        }
    }
}

// MARK: - Tiles, dots, pills

/// A row glyph in a tile, so rows align whatever the symbol width.
struct IconTile: View {
    let symbol: String
    var size: CGFloat = House.Control.tile

    var body: some View {
        RoundedRectangle(cornerRadius: House.Radius.tile, style: .continuous)
            .fill(House.ColorToken.tileFill)
            .overlay(
                RoundedRectangle(cornerRadius: House.Radius.tile, style: .continuous)
                    .strokeBorder(House.ColorToken.tileStroke, lineWidth: House.hairline)
            )
            .overlay(
                Image(systemName: symbol)
                    .font(.system(size: size * 0.46, weight: .regular))
                    .foregroundStyle(House.ColorToken.textSecondary)
            )
            .frame(width: size, height: size)
    }
}

/// The one piece of colour on any Local Models surface: a status dot. Always paired
/// with a word, never colour alone.
struct StatusDot: View {
    var tint: Color = House.ColorToken.success
    var diameter: CGFloat = 6

    var body: some View {
        Circle()
            .fill(tint)
            .frame(width: diameter, height: diameter)
    }
}

/// "Granted", "Warm": an outlined pill with a 6 px status dot.
struct StatusPill: View {
    let text: String
    var tint: Color = House.ColorToken.success

    var body: some View {
        HStack(spacing: House.Spacing.xxs) {
            StatusDot(tint: tint)
            Text(text)
                .font(House.TypeToken.meta)
                .foregroundStyle(House.ColorToken.textSecondary)
        }
        .padding(.horizontal, House.Spacing.xs)
        .frame(height: House.Control.chip)
        .overlay(
            RoundedRectangle(cornerRadius: House.Radius.sm, style: .continuous)
                .strokeBorder(House.ColorToken.keyCapStroke, lineWidth: House.hairline)
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel(text)
    }
}

/// A done mark: an 18 px ink disc with an ink-inverse check. Not-done is the
/// same disc as a quiet outline, so the pair reads without colour.
struct DoneDisc: View {
    let done: Bool

    var body: some View {
        ZStack {
            if done {
                Circle().fill(House.ColorToken.textPrimary)
                Image(systemName: "checkmark")
                    .font(.system(size: House.TypeToken.Size.micro, weight: .bold))
                    .foregroundStyle(House.ColorToken.textInverse)
            } else {
                Circle().strokeBorder(House.ColorToken.keyCapStroke, lineWidth: House.hairline)
            }
        }
        .frame(width: 18, height: 18)
        .accessibilityLabel(done ? "Done" : "Not done")
    }
}

/// A small outlined action chip ("Record", "Enable").
struct HouseChipButtonStyle: ButtonStyle {
    var destructive = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(House.TypeToken.meta)
            .foregroundStyle(destructive ? House.ColorToken.danger : House.ColorToken.textPrimary)
            .padding(.horizontal, House.Spacing.sm)
            .frame(height: House.Control.tile)
            .background(
                RoundedRectangle(cornerRadius: House.Radius.tile, style: .continuous)
                    .fill(configuration.isPressed ? House.ColorToken.selectionFill : House.ColorToken.keyCapFill)
            )
            .overlay(
                RoundedRectangle(cornerRadius: House.Radius.tile, style: .continuous)
                    .strokeBorder(House.ColorToken.keyCapStroke, lineWidth: House.hairline)
            )
            .contentShape(Rectangle())
    }
}

/// The primary action: an ink fill with inverse ink text. Never accent.
struct HouseInkButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(House.TypeToken.label)
            .foregroundStyle(House.ColorToken.textInverse)
            .padding(.horizontal, House.Spacing.md)
            .frame(height: House.Control.chip)
            .background(
                RoundedRectangle(cornerRadius: House.Radius.tile, style: .continuous)
                    .fill(House.ColorToken.textPrimary.opacity(configuration.isPressed ? 0.8 : 1))
            )
            .contentShape(Rectangle())
    }
}

/// A quiet text action, for links and secondary verbs.
struct HouseLinkButtonStyle: ButtonStyle {
    var destructive = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(House.TypeToken.meta)
            .foregroundStyle(destructive ? House.ColorToken.danger : House.ColorToken.accent)
            .opacity(configuration.isPressed ? 0.7 : 1)
            .contentShape(Rectangle())
    }
}

// MARK: - Ink toggle

/// The switch itself: ink when on, a quiet tile when off. Never blue.
struct InkSwitch: View {
    @Binding var isOn: Bool
    var enabled = true

    private static let trackWidth: CGFloat = 38
    private static let trackHeight: CGFloat = 22
    private static let knob: CGFloat = 16

    var body: some View {
        Button {
            guard enabled else { return }
            isOn.toggle()
        } label: {
            InkSwitchTrack(isOn: isOn, enabled: enabled)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .accessibilityAddTraits(isOn ? [.isButton, .isSelected] : .isButton)
        .accessibilityValue(isOn ? "On" : "Off")
    }
}

/// The switch's painted track, shared by `InkSwitch` and `InkToggleStyle`.
struct InkSwitchTrack: View {
    let isOn: Bool
    var enabled = true

    var body: some View {
        ZStack(alignment: isOn ? .trailing : .leading) {
            Capsule()
                .fill(isOn ? House.ColorToken.textPrimary : House.ColorToken.tileFill)
                .overlay(
                    Capsule().strokeBorder(
                        isOn ? Color.clear : House.ColorToken.tileStroke,
                        lineWidth: House.hairline
                    )
                )
            Circle()
                .fill(isOn ? House.ColorToken.textInverse : House.ColorToken.textTertiary)
                .frame(width: 16, height: 16)
                .padding(.horizontal, 3)
        }
        .frame(width: 38, height: 22)
        .opacity(enabled ? 1 : 0.45)
        .animation(.easeOut(duration: House.Motion.hover), value: isOn)
    }
}

/// The house toggle style, for call sites that keep SwiftUI's `Toggle`.
struct InkToggleStyle: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: House.Spacing.sm) {
            configuration.label
                .font(House.TypeToken.label)
                .foregroundStyle(House.ColorToken.textPrimary)
                .frame(maxWidth: .infinity, alignment: .leading)
            InkSwitch(isOn: configuration.$isOn)
        }
    }
}

/// A toggle for a capability Local Models cannot honour yet: shown, off, and inert.
struct InertToggle: View {
    var body: some View {
        InkSwitchTrack(isOn: false, enabled: false)
    }
}

// MARK: - Cards and rows

/// A settings group: a card at `Radius.lg` on `surfaceRaised` with `stroke`
/// and a 1 px top highlight. The uppercase `section` label is the card's first
/// row, with an optional counter on the right, exactly as the mockup draws it.
struct SlateCard<Content: View>: View {
    var section: String?
    /// A short right-hand fact on the header row ("4 of 5 complete").
    var counter: String?
    /// A full-width line of purpose under the header row.
    var footnote: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let section {
                HStack(spacing: House.Spacing.sm) {
                    Text(section.uppercased())
                        .font(House.TypeToken.section)
                        .tracking(House.TypeToken.Tracking.section)
                        .foregroundStyle(House.ColorToken.textTertiary)
                    Spacer(minLength: House.Spacing.xs)
                    if let counter {
                        Text(counter)
                            .font(House.TypeToken.meta)
                            .foregroundStyle(House.ColorToken.textTertiary)
                            .lineLimit(1)
                    }
                }
                .padding(.horizontal, House.Spacing.md)
                .padding(.top, House.Spacing.sm)
                .padding(.bottom, House.Spacing.xs)
                SlateDivider()
            }
            if let footnote {
                SlateBlock {
                    Text(footnote)
                        .font(House.TypeToken.meta)
                        .foregroundStyle(House.ColorToken.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                SlateDivider()
            }
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: House.Radius.lg, style: .continuous)
                .fill(House.ColorToken.surfaceRaised)
        )
        .overlay(
            RoundedRectangle(cornerRadius: House.Radius.lg, style: .continuous)
                .strokeBorder(House.ColorToken.stroke, lineWidth: House.hairline)
        )
        .overlay(alignment: .top) {
            House.ColorToken.highlightTop
                .frame(height: House.hairline)
                .padding(.horizontal, House.Radius.lg / 2)
        }
    }
}

/// One card row: `label` title, optional `meta` detail, trailing control.
/// Rows are 38–48 high and split by `divider`.
struct SlateRow<Trailing: View>: View {
    var title: String?
    var detail: String?
    var minHeight: CGFloat = 44
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(alignment: .center, spacing: House.Spacing.sm) {
            if title != nil || detail != nil {
                VStack(alignment: .leading, spacing: 2) {
                    if let title {
                        Text(title)
                            .font(House.TypeToken.label)
                            .foregroundStyle(House.ColorToken.textPrimary)
                    }
                    if let detail {
                        Text(detail)
                            .font(House.TypeToken.meta)
                            .foregroundStyle(House.ColorToken.textTertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: House.Spacing.sm)
            }
            trailing
        }
        .padding(.horizontal, House.Spacing.md)
        .padding(.vertical, House.Spacing.sm)
        .frame(minHeight: minHeight)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

extension SlateRow where Trailing == EmptyView {
    init(title: String? = nil, detail: String? = nil, minHeight: CGFloat = 44) {
        self.init(title: title, detail: detail, minHeight: minHeight) { EmptyView() }
    }
}

/// A free-form row: arbitrary content on the card's row grid.
struct SlateBlock<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: House.Spacing.xs) {
            content
        }
        .padding(.horizontal, House.Spacing.md)
        .padding(.vertical, House.Spacing.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The line between rows. Quieter than the panel stroke, and inset to the
/// card's horizontal padding so it reads as a row rule, not a panel edge.
struct SlateDivider: View {
    var inset: CGFloat = House.Spacing.md

    var body: some View {
        House.ColorToken.divider
            .frame(height: House.hairline)
            .padding(.horizontal, inset)
    }
}

/// Prose inside a card, at `bodySmall` with the scale's line height.
struct SlateProse: View {
    let text: String
    var tertiary = false

    init(_ text: String, tertiary: Bool = false) {
        self.text = text
        self.tertiary = tertiary
    }

    var body: some View {
        Text(text)
            .font(House.TypeToken.bodySmall)
            .foregroundStyle(tertiary ? House.ColorToken.textTertiary : House.ColorToken.textSecondary)
            // `LineHeight` is the total multiple; the font already supplies
            // about 1.25 of it, so only the remainder is extra leading.
            .lineSpacing(House.TypeToken.Size.bodySmall * (House.TypeToken.LineHeight.bodySmall - 1.25))
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A two-column identifier row: `meta` label left, `code` value right.
struct SlateInfoRow: View {
    var title: String
    var value: String
    var monospaced = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: House.Spacing.sm) {
            Text(title)
                .font(House.TypeToken.meta)
                .foregroundStyle(House.ColorToken.textTertiary)
                .frame(minWidth: 108, alignment: .leading)
            Text(value)
                .font(monospaced ? House.TypeToken.code : House.TypeToken.meta)
                .foregroundStyle(House.ColorToken.textSecondary)
                .textSelection(.enabled)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: 0)
        }
    }
}

// MARK: - Pane header and footer

/// The pane header: 60 high, `heading` title with a one-line `meta` purpose.
struct PaneHeader: View {
    let title: String
    let purpose: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(House.TypeToken.heading)
                .foregroundStyle(House.ColorToken.textPrimary)
            Text(purpose)
                .font(House.TypeToken.meta)
                .foregroundStyle(House.ColorToken.textTertiary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, minHeight: 60, alignment: .leading)
        .padding(.horizontal, House.Spacing.lg)
    }
}

/// The footer well: a sunken bar with status on the left and the primary key
/// hints on the right.
struct FooterWell<Leading: View, Trailing: View>: View {
    var height: CGFloat = House.Control.footer
    @ViewBuilder var leading: Leading
    @ViewBuilder var trailing: Trailing

    var body: some View {
        VStack(spacing: 0) {
            SlateDivider()
            HStack(spacing: House.Spacing.sm) {
                leading
                Spacer(minLength: House.Spacing.sm)
                trailing
            }
            .padding(.horizontal, House.Spacing.md)
            .frame(height: height - House.hairline)
            .background(House.ColorToken.well)
        }
        .frame(height: height)
    }
}

/// The footer's left half: a status dot and a line of context.
struct FooterStatus: View {
    let text: String
    var tint: Color = House.ColorToken.success

    var body: some View {
        HStack(spacing: House.Spacing.xs) {
            StatusDot(tint: tint)
            Text(text)
                .font(House.TypeToken.meta)
                .foregroundStyle(House.ColorToken.textTertiary)
                .lineLimit(1)
        }
    }
}

// MARK: - Rail

/// A settings rail row: a 24 px icon tile, a `label` title, and the section's
/// key hint. Selected is a raised tile with an inset ring and a 1 px drop;
/// hover is half the selection fill.
struct RailRow: View {
    let symbol: String
    let title: String
    let isSelected: Bool
    let action: () -> Void

    @State private var isHovering = false
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Button(action: action) {
            HStack(spacing: House.Spacing.xs) {
                IconTile(symbol: symbol, size: 24)
                Text(title)
                    .font(House.TypeToken.label)
                    .foregroundStyle(House.ColorToken.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: House.Spacing.xxs)
            }
            .padding(.horizontal, House.Spacing.xs)
            .frame(height: 34)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(selectionBackground)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { isHovering = $0 }
        .accessibilityAddTraits(isSelected ? [.isButton, .isSelected] : .isButton)
    }

    @ViewBuilder
    private var selectionBackground: some View {
        let shape = RoundedRectangle(cornerRadius: House.Radius.md, style: .continuous)
        if isSelected {
            shape
                .fill(House.ColorToken.surfaceRaised)
                .overlay(shape.strokeBorder(House.ColorToken.selectionRing, lineWidth: House.hairline))
                .houseShadow(House.Shadow.selection, dark: scheme == .dark)
        } else if isHovering {
            shape.fill(House.ColorToken.hoverFill)
        } else {
            shape.fill(Color.clear)
        }
    }
}

/// The rail's app mark: a 28 px tile plus the app name over a `section` label.
struct AppMark: View {
    let symbol: String
    let name: String
    let caption: String

    var body: some View {
        HStack(spacing: House.Spacing.xs) {
            RoundedRectangle(cornerRadius: House.Radius.md, style: .continuous)
                .fill(House.ColorToken.textPrimary)
                .overlay(
                    Image(systemName: symbol)
                        .font(.system(size: House.TypeToken.Size.body, weight: .medium))
                        .foregroundStyle(House.ColorToken.textInverse)
                )
                .frame(width: 28, height: 28)
            VStack(alignment: .leading, spacing: 1) {
                Text(name)
                    .font(House.TypeToken.label)
                    .foregroundStyle(House.ColorToken.textPrimary)
                Text(caption.uppercased())
                    .font(House.TypeToken.section)
                    .tracking(House.TypeToken.Tracking.section)
                    .foregroundStyle(House.ColorToken.textTertiary)
            }
            Spacer(minLength: 0)
        }
    }
}

// MARK: - Segmented control

/// The house segmented control. The system's `.segmented` picker paints the
/// selected segment with the system accent (blue), which Slate forbids, so the
/// selection is the same raised tile the rail uses.
struct SlateSegmented<Value: Hashable>: View {
    let options: [(value: Value, title: String)]
    @Binding var selection: Value

    @Environment(\.colorScheme) private var scheme

    var body: some View {
        HStack(spacing: 2) {
            ForEach(Array(options.enumerated()), id: \.offset) { _, option in
                Button {
                    selection = option.value
                } label: {
                    Text(option.title)
                        .font(House.TypeToken.meta)
                        .foregroundStyle(
                            selection == option.value
                                ? House.ColorToken.textPrimary
                                : House.ColorToken.textSecondary
                        )
                        .padding(.horizontal, House.Spacing.sm)
                        .frame(maxWidth: .infinity)
                        .frame(height: House.Control.tile)
                        .background(background(isSelected: selection == option.value))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selection == option.value ? [.isButton, .isSelected] : .isButton)
            }
        }
        .padding(2)
        .background(
            RoundedRectangle(cornerRadius: House.Radius.md, style: .continuous)
                .fill(House.ColorToken.well)
        )
        .overlay(
            RoundedRectangle(cornerRadius: House.Radius.md, style: .continuous)
                .strokeBorder(House.ColorToken.stroke, lineWidth: House.hairline)
        )
    }

    @ViewBuilder
    private func background(isSelected: Bool) -> some View {
        let shape = RoundedRectangle(cornerRadius: House.Radius.sm, style: .continuous)
        if isSelected {
            shape
                .fill(House.ColorToken.surfaceRaised)
                .overlay(shape.strokeBorder(House.ColorToken.selectionRing, lineWidth: House.hairline))
                .houseShadow(House.Shadow.selection, dark: scheme == .dark)
        } else {
            shape.fill(Color.clear)
        }
    }
}
