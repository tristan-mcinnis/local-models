import AppKit
import SwiftUI
import HouseDesign
import HouseUIKit

// The menu-bar surface, following the "Menu bar panel" component in
// design-system/DESIGN.md: a 300 px glass panel in place of an NSMenu, a header
// with a status dot and the one master switch, 36 px rows, a second group for
// the rarer actions, and a footer well. The row, note and window plumbing is
// the shared kit in MenuBarPanel.swift.
//
// What is different here: the first group is the registry rather than a fixed
// list of verbs, so its rows carry a model id, its capabilities, and whether
// the daemon is holding it in memory. Return warms the selected model and
// ⌘Return unloads it.

/// One 36 px model row: an icon tile, the model id in `label`, its
/// capabilities in `meta`, and either the warm chip or the load hint.
struct ModelPanelRow: View {
    let model: ModelRow
    let isSelected: Bool
    let isBusy: Bool
    let isEnabled: Bool
    let onHover: () -> Void
    let onTap: () -> Void

    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: House.Spacing.sm) {
                IconTile(symbol: glyph)
                VStack(alignment: .leading, spacing: 1) {
                    Text(model.id)
                        .font(House.TypeToken.label)
                        .foregroundStyle(House.ColorToken.textPrimary)
                        .lineLimit(1)
                    Text(model.detail)
                        .font(House.TypeToken.meta)
                        .foregroundStyle(House.ColorToken.textTertiary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                Spacer(minLength: House.Spacing.xs)
                trailing
            }
            .padding(.horizontal, House.Spacing.sm)
            .frame(height: House.Control.railRow)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(background)
            .contentShape(Rectangle())
            .opacity(isEnabled ? 1 : 0.45)
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .onHover { if $0 { onHover() } }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            [model.id, model.warm ? "warm" : "not loaded", model.idleLabel]
                .compactMap { $0 }
                .joined(separator: ", ")
        )
        .accessibilityAddTraits(isSelected ? [.isButton, .isSelected] : .isButton)
    }

    /// The glyph names what the model does, from the same SF family as the
    /// chip in the app icon.
    private var glyph: String {
        let caps = Set(model.capabilities)
        if caps.contains("vision") || caps.contains("image") { return "eye" }
        if caps.contains("audio") || caps.contains("transcribe") { return "waveform" }
        if caps.contains("completion") { return "text.cursor" }
        return "cpu"
    }

    @ViewBuilder
    private var trailing: some View {
        if isBusy {
            Text("Loading…")
                .font(House.TypeToken.meta)
                .foregroundStyle(House.ColorToken.textTertiary)
        } else if model.warm {
            StatusPill(text: "Warm")
        } else if !model.backendAvailable {
            Text("No backend")
                .font(House.TypeToken.meta)
                .foregroundStyle(House.ColorToken.textTertiary)
        } else {
            Text("Load")
                .font(House.TypeToken.meta)
                .foregroundStyle(House.ColorToken.textSecondary)
        }
    }

    @ViewBuilder
    private var background: some View {
        let shape = RoundedRectangle(cornerRadius: House.Radius.row, style: .continuous)
        if isSelected && isEnabled {
            shape
                .fill(House.ColorToken.selectionFill)
                .overlay(shape.strokeBorder(House.ColorToken.selectionRing, lineWidth: House.hairline))
                .houseShadow(House.Shadow.selection, dark: scheme == .dark)
        } else {
            shape.fill(Color.clear)
        }
    }
}

/// The one VOICE row: local-tts's own glyph, id and endpoint, and a status
/// pill in place of the model rows' warm chip. Return speaks a short
/// greeting through the service.
struct VoicePanelRow: View {
    let isSelected: Bool
    let isBusy: Bool
    let isReady: Bool
    let detail: String
    let onHover: () -> Void
    let onTap: () -> Void

    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: House.Spacing.sm) {
                IconTile(symbol: "waveform")
                VStack(alignment: .leading, spacing: 1) {
                    Text("Local TTS")
                        .font(House.TypeToken.label)
                        .foregroundStyle(House.ColorToken.textPrimary)
                        .lineLimit(1)
                    Text(detail)
                        .font(House.TypeToken.meta)
                        .foregroundStyle(House.ColorToken.textTertiary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                Spacer(minLength: House.Spacing.xs)
                trailing
            }
            .padding(.horizontal, House.Spacing.sm)
            .frame(height: House.Control.railRow)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(background)
            .contentShape(Rectangle())
            .opacity(isReady ? 1 : 0.45)
        }
        .buttonStyle(.plain)
        .disabled(!isReady)
        .onHover { if $0 { onHover() } }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Local TTS, \(isReady ? "ready" : "down")")
        .accessibilityAddTraits(isSelected ? [.isButton, .isSelected] : .isButton)
    }

    @ViewBuilder
    private var trailing: some View {
        if isBusy {
            Text("Speaking…")
                .font(House.TypeToken.meta)
                .foregroundStyle(House.ColorToken.textTertiary)
        } else if isReady {
            StatusPill(text: "Ready", tint: House.ColorToken.success)
        } else {
            StatusPill(text: "Down", tint: House.ColorToken.danger)
        }
    }

    @ViewBuilder
    private var background: some View {
        let shape = RoundedRectangle(cornerRadius: House.Radius.row, style: .continuous)
        if isSelected && isReady {
            shape
                .fill(House.ColorToken.selectionFill)
                .overlay(shape.strokeBorder(House.ColorToken.selectionRing, lineWidth: House.hairline))
                .houseShadow(House.Shadow.selection, dark: scheme == .dark)
        } else {
            shape.fill(Color.clear)
        }
    }
}

// MARK: - The panel

struct MenuBarPanelView: View {
    @ObservedObject var model: PanelModel

    /// The panel width from the mockup.
    static let width: CGFloat = 300

    var body: some View {
        HouseGlass(radius: House.Radius.lg) {
            VStack(spacing: 0) {
                header
                SlateDivider()
                rows
                FooterWell(height: 36) {
                    footerButton(
                        index: model.footerSelectionBase,
                        title: "Settings", chord: "⌘ ,", run: model.onOpenSettings
                    )
                } trailing: {
                    footerButton(
                        index: model.footerSelectionBase + 1,
                        title: "Quit", chord: "⌘ Q", run: model.onQuit
                    )
                }
            }
        }
        .frame(width: Self.width)
        .padding(House.Spacing.md)
    }

    // MARK: Header

    /// 26 px icon tile, the app name in `label`, a status line in `caption`
    /// with a 6 px dot, and the ink toggle for the one master switch: the
    /// daemon itself.
    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: House.Spacing.sm) {
                IconTile(symbol: "cpu")
                VStack(alignment: .leading, spacing: 1) {
                    Text("Local Models")
                        .font(House.TypeToken.label)
                        .foregroundStyle(House.ColorToken.textPrimary)
                    HStack(spacing: House.Spacing.xxs) {
                        StatusDot(tint: dotTint)
                        Text(model.headline)
                            .font(House.TypeToken.caption)
                            .foregroundStyle(House.ColorToken.textTertiary)
                            .lineLimit(1)
                    }
                }
                Spacer(minLength: House.Spacing.xs)
                InkSwitch(isOn: Binding(
                    get: { model.daemonUp },
                    set: { model.setDaemonRunning($0) }
                ))
                .accessibilityLabel("Run the local-models daemon")
            }
            // Where the daemon answers, or why it cannot be reached. It does
            // not fit beside the dot at 300 px, so it sits under the header on
            // its own dim line, the way Memory draws its collector context.
            if let context = model.context {
                Text(context)
                    .font(House.TypeToken.caption)
                    .foregroundStyle(House.ColorToken.textTertiary)
                    .lineLimit(1)
                    .padding(.leading, House.Control.tile + House.Spacing.sm)
            }
        }
        .padding(.horizontal, House.Spacing.sm)
        .padding(.vertical, House.Spacing.sm)
    }

    private var dotTint: Color {
        switch model.health {
        case .running: return House.ColorToken.success
        case .down: return House.ColorToken.danger
        case .unknown: return House.ColorToken.textTertiary
        }
    }

    // MARK: Rows

    private var rows: some View {
        VStack(spacing: 2) {
            if model.models.isEmpty {
                PanelNote(text: emptyNote, verticalPadding: House.Spacing.xs)
            } else {
                ForEach(Array(model.models.enumerated()), id: \.element.id) { index, entry in
                    ModelPanelRow(
                        model: entry,
                        isSelected: model.selection == index,
                        isBusy: model.busy == entry.id,
                        isEnabled: model.daemonUp && entry.backendAvailable,
                        onHover: { model.selection = index },
                        onTap: {
                            model.selection = index
                            model.runSelection()
                        }
                    )
                }
            }
            SlateDivider().padding(.vertical, House.Spacing.xxs)
            ForEach(Array(model.moreActions.enumerated()), id: \.element.id) { index, action in
                PanelRow(
                    action: action,
                    isSelected: model.selection == model.models.count + index,
                    onHover: { model.selection = model.models.count + index },
                    onTap: action.run,
                    glyphWidth: House.Control.tile
                )
            }
            SlateDivider().padding(.vertical, House.Spacing.xxs)
            PanelSectionLabel(text: "Voice", topPadding: House.Spacing.xxs)
            VoicePanelRow(
                isSelected: model.selection == model.voiceRowIndex,
                isBusy: model.busy == "local-tts",
                isReady: model.ttsUp,
                detail: model.voiceDetail,
                onHover: { model.selection = model.voiceRowIndex },
                onTap: {
                    model.selection = model.voiceRowIndex
                    model.runSelection()
                }
            )
        }
        .padding(.horizontal, House.Spacing.xs)
        .padding(.vertical, House.Spacing.xs)
    }

    private var emptyNote: String {
        if model.isRefreshing { return "Asking the daemon…" }
        if !model.daemonUp { return "Start the daemon to see the registry." }
        return "No models registered in ~/Models/models.json."
    }

    // MARK: Footer

    private func footerButton(index: Int, title: String, chord: String, run: @escaping () -> Void) -> some View {
        Button(action: run) {
            KeyHint(title: title, chord: chord)
                .padding(.horizontal, House.Spacing.xxs)
                .padding(.vertical, 2)
                .background(
                    RoundedRectangle(cornerRadius: House.Radius.sm, style: .continuous)
                        .fill(model.selection == index ? House.ColorToken.selectionFill : Color.clear)
                )
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { if $0 { model.selection = index } }
    }
}
