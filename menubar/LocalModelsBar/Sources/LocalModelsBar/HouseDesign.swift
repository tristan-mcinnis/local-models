// GENERATED from design-system/tokens.json fe2b0cd6e404; do not edit
// Source of truth: the design-system repo (DESIGN.md + tokens.json).
// Regenerate with `make swift` there; `make check` verifies this copy.

import SwiftUI
#if canImport(AppKit)
import AppKit
#elseif canImport(UIKit)
import UIKit
#endif

/// House design tokens. Semantic names only; colours adapt to the
/// window appearance (light / dark) without per-view code.
enum House {
#if canImport(AppKit)
    /// AppKit colours, one per token, resolved per appearance.
    enum NSColorToken {
        /// Opaque window ground (Settings, History).
        static let surface = adaptive(
            light: NSColor(srgbRed: 0.9686, green: 0.9686, blue: 0.9647, alpha: 1.0),
            dark: NSColor(srgbRed: 0.102, green: 0.1059, blue: 0.1216, alpha: 1.0)
        )
        /// Raised cards and composers that sit above the ground.
        static let surfaceRaised = adaptive(
            light: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 1.0),
            dark: NSColor(srgbRed: 0.1294, green: 0.1333, blue: 0.1529, alpha: 1.0)
        )
        /// Opaque rails and tracks that sit below the ground.
        static let surfaceSunken = adaptive(
            light: NSColor(srgbRed: 0.9412, green: 0.9412, blue: 0.9373, alpha: 1.0),
            dark: NSColor(srgbRed: 0.0784, green: 0.0824, blue: 0.0941, alpha: 1.0)
        )
        /// Quiet grouped fill painted over any ground (rail, card body).
        static let surfaceTint = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.045),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.06)
        )
        /// Sunken footer or bar well painted over a panel.
        static let well = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.035),
            dark: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.22)
        )
        /// 26 px icon tile behind a row glyph.
        static let tileFill = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.045),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.06)
        )
        /// Hairline around an icon tile.
        static let tileStroke = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.05),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.06)
        )
        /// Model, context, and session chips.
        static let chipFill = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.05),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.06)
        )
        /// Ink. Warm near-black on light, warm near-white on dark.
        static let textPrimary = adaptive(
            light: NSColor(srgbRed: 0.1098, green: 0.1059, blue: 0.102, alpha: 1.0),
            dark: NSColor(srgbRed: 0.9294, green: 0.9216, blue: 0.9098, alpha: 1.0)
        )
        /// Ink at 60 %. Supporting text; tracks any ground.
        static let textSecondary = adaptive(
            light: NSColor(srgbRed: 0.1098, green: 0.1059, blue: 0.102, alpha: 0.62),
            dark: NSColor(srgbRed: 0.9294, green: 0.9216, blue: 0.9098, alpha: 0.6)
        )
        /// Ink at 40 %. Metadata, placeholders, section labels.
        static let textTertiary = adaptive(
            light: NSColor(srgbRed: 0.1098, green: 0.1059, blue: 0.102, alpha: 0.5),
            dark: NSColor(srgbRed: 0.9294, green: 0.9216, blue: 0.9098, alpha: 0.4)
        )
        /// Text on the HUD or on an ink-filled control.
        static let textInverse = adaptive(
            light: NSColor(srgbRed: 0.949, green: 0.949, blue: 0.9608, alpha: 1.0),
            dark: NSColor(srgbRed: 0.0667, green: 0.0667, blue: 0.0784, alpha: 1.0)
        )
        /// Focus rings and links only. Never chrome, never a button fill.
        static let accent = adaptive(
            light: NSColor(srgbRed: 0.2314, green: 0.3569, blue: 0.8588, alpha: 1.0),
            dark: NSColor(srgbRed: 0.6157, green: 0.7059, blue: 1.0, alpha: 1.0)
        )
        /// Tinted fill behind an accent label.
        static let accentSoft = adaptive(
            light: NSColor(srgbRed: 0.2314, green: 0.3569, blue: 0.8588, alpha: 0.12),
            dark: NSColor(srgbRed: 0.6157, green: 0.7059, blue: 1.0, alpha: 0.16)
        )
        /// Status dot: ready, on, landed.
        static let success = adaptive(
            light: NSColor(srgbRed: 0.1804, green: 0.6078, blue: 0.4039, alpha: 1.0),
            dark: NSColor(srgbRed: 0.498, green: 0.8196, blue: 0.651, alpha: 1.0)
        )
        /// Status only.
        static let warning = adaptive(
            light: NSColor(srgbRed: 0.7216, green: 0.4627, blue: 0.0392, alpha: 1.0),
            dark: NSColor(srgbRed: 0.9608, green: 0.7216, blue: 0.2902, alpha: 1.0)
        )
        /// Status dot: off, error, recording. Destructive actions.
        static let danger = adaptive(
            light: NSColor(srgbRed: 0.7529, green: 0.2235, blue: 0.1686, alpha: 1.0),
            dark: NSColor(srgbRed: 1.0, green: 0.4196, blue: 0.3686, alpha: 1.0)
        )
        /// Hairline around a panel or card.
        static let stroke = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.06),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.1)
        )
        /// Focused or selected hairline.
        static let strokeStrong = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.14),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.16)
        )
        /// Line between rows and sections. Quieter than the panel stroke.
        static let divider = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.06),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.07)
        )
        /// 1 px inset highlight along the top edge of a panel or raised card.
        static let highlightTop = adaptive(
            light: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.9),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.05)
        )
        /// Selected row fill.
        static let selectionFill = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.055),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.09)
        )
        /// Inset ring on the selected row.
        static let selectionRing = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.06),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.06)
        )
        /// Hover feedback. Half the selection fill.
        static let hoverFill = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.03),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.045)
        )
        /// Key caps are outlined, not filled.
        static let keyCapFill = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.0),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.0)
        )
        /// 1 px outline of a key cap.
        static let keyCapStroke = adaptive(
            light: NSColor(srgbRed: 0.0, green: 0.0, blue: 0.0, alpha: 0.14),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.14)
        )
        /// Tint over the blur material of a floating panel or the pill.
        static let panelTint = adaptive(
            light: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.88),
            dark: NSColor(srgbRed: 0.102, green: 0.1059, blue: 0.1216, alpha: 0.9)
        )
        /// Opaque dark HUD for full-screen overlays (Type to Click). Same in both modes.
        static let hudFill = adaptive(
            light: NSColor(srgbRed: 0.0706, green: 0.0706, blue: 0.0784, alpha: 0.95),
            dark: NSColor(srgbRed: 0.0706, green: 0.0706, blue: 0.0784, alpha: 0.95)
        )
        /// Text on the HUD.
        static let hudText = adaptive(
            light: NSColor(srgbRed: 0.949, green: 0.949, blue: 0.9608, alpha: 1.0),
            dark: NSColor(srgbRed: 0.949, green: 0.949, blue: 0.9608, alpha: 1.0)
        )
        /// Hairline on the HUD.
        static let hudStroke = adaptive(
            light: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.1),
            dark: NSColor(srgbRed: 1.0, green: 1.0, blue: 1.0, alpha: 0.1)
        )
        /// Busy or idle marks on the HUD.
        static let hudMuted = adaptive(
            light: NSColor(srgbRed: 0.549, green: 0.5804, blue: 0.6196, alpha: 1.0),
            dark: NSColor(srgbRed: 0.549, green: 0.5804, blue: 0.6196, alpha: 1.0)
        )

        static func adaptive(light: NSColor, dark: NSColor) -> NSColor {
            NSColor(name: nil) { appearance in
                appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? dark : light
            }
        }
    }

    /// SwiftUI colours wrapping `NSColorToken`.
    enum ColorToken {
        static let surface = Color(nsColor: NSColorToken.surface)
        static let surfaceRaised = Color(nsColor: NSColorToken.surfaceRaised)
        static let surfaceSunken = Color(nsColor: NSColorToken.surfaceSunken)
        static let surfaceTint = Color(nsColor: NSColorToken.surfaceTint)
        static let well = Color(nsColor: NSColorToken.well)
        static let tileFill = Color(nsColor: NSColorToken.tileFill)
        static let tileStroke = Color(nsColor: NSColorToken.tileStroke)
        static let chipFill = Color(nsColor: NSColorToken.chipFill)
        static let textPrimary = Color(nsColor: NSColorToken.textPrimary)
        static let textSecondary = Color(nsColor: NSColorToken.textSecondary)
        static let textTertiary = Color(nsColor: NSColorToken.textTertiary)
        static let textInverse = Color(nsColor: NSColorToken.textInverse)
        static let accent = Color(nsColor: NSColorToken.accent)
        static let accentSoft = Color(nsColor: NSColorToken.accentSoft)
        static let success = Color(nsColor: NSColorToken.success)
        static let warning = Color(nsColor: NSColorToken.warning)
        static let danger = Color(nsColor: NSColorToken.danger)
        static let stroke = Color(nsColor: NSColorToken.stroke)
        static let strokeStrong = Color(nsColor: NSColorToken.strokeStrong)
        static let divider = Color(nsColor: NSColorToken.divider)
        static let highlightTop = Color(nsColor: NSColorToken.highlightTop)
        static let selectionFill = Color(nsColor: NSColorToken.selectionFill)
        static let selectionRing = Color(nsColor: NSColorToken.selectionRing)
        static let hoverFill = Color(nsColor: NSColorToken.hoverFill)
        static let keyCapFill = Color(nsColor: NSColorToken.keyCapFill)
        static let keyCapStroke = Color(nsColor: NSColorToken.keyCapStroke)
        static let panelTint = Color(nsColor: NSColorToken.panelTint)
        static let hudFill = Color(nsColor: NSColorToken.hudFill)
        static let hudText = Color(nsColor: NSColorToken.hudText)
        static let hudStroke = Color(nsColor: NSColorToken.hudStroke)
        static let hudMuted = Color(nsColor: NSColorToken.hudMuted)
    }
#elseif canImport(UIKit)
    /// UIKit colours, one per token, resolved per trait collection.
    enum UIColorToken {
        /// Opaque window ground (Settings, History).
        static let surface = adaptive(
            light: UIColor(red: 0.9686, green: 0.9686, blue: 0.9647, alpha: 1.0),
            dark: UIColor(red: 0.102, green: 0.1059, blue: 0.1216, alpha: 1.0)
        )
        /// Raised cards and composers that sit above the ground.
        static let surfaceRaised = adaptive(
            light: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 1.0),
            dark: UIColor(red: 0.1294, green: 0.1333, blue: 0.1529, alpha: 1.0)
        )
        /// Opaque rails and tracks that sit below the ground.
        static let surfaceSunken = adaptive(
            light: UIColor(red: 0.9412, green: 0.9412, blue: 0.9373, alpha: 1.0),
            dark: UIColor(red: 0.0784, green: 0.0824, blue: 0.0941, alpha: 1.0)
        )
        /// Quiet grouped fill painted over any ground (rail, card body).
        static let surfaceTint = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.045),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.06)
        )
        /// Sunken footer or bar well painted over a panel.
        static let well = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.035),
            dark: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.22)
        )
        /// 26 px icon tile behind a row glyph.
        static let tileFill = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.045),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.06)
        )
        /// Hairline around an icon tile.
        static let tileStroke = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.05),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.06)
        )
        /// Model, context, and session chips.
        static let chipFill = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.05),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.06)
        )
        /// Ink. Warm near-black on light, warm near-white on dark.
        static let textPrimary = adaptive(
            light: UIColor(red: 0.1098, green: 0.1059, blue: 0.102, alpha: 1.0),
            dark: UIColor(red: 0.9294, green: 0.9216, blue: 0.9098, alpha: 1.0)
        )
        /// Ink at 60 %. Supporting text; tracks any ground.
        static let textSecondary = adaptive(
            light: UIColor(red: 0.1098, green: 0.1059, blue: 0.102, alpha: 0.62),
            dark: UIColor(red: 0.9294, green: 0.9216, blue: 0.9098, alpha: 0.6)
        )
        /// Ink at 40 %. Metadata, placeholders, section labels.
        static let textTertiary = adaptive(
            light: UIColor(red: 0.1098, green: 0.1059, blue: 0.102, alpha: 0.5),
            dark: UIColor(red: 0.9294, green: 0.9216, blue: 0.9098, alpha: 0.4)
        )
        /// Text on the HUD or on an ink-filled control.
        static let textInverse = adaptive(
            light: UIColor(red: 0.949, green: 0.949, blue: 0.9608, alpha: 1.0),
            dark: UIColor(red: 0.0667, green: 0.0667, blue: 0.0784, alpha: 1.0)
        )
        /// Focus rings and links only. Never chrome, never a button fill.
        static let accent = adaptive(
            light: UIColor(red: 0.2314, green: 0.3569, blue: 0.8588, alpha: 1.0),
            dark: UIColor(red: 0.6157, green: 0.7059, blue: 1.0, alpha: 1.0)
        )
        /// Tinted fill behind an accent label.
        static let accentSoft = adaptive(
            light: UIColor(red: 0.2314, green: 0.3569, blue: 0.8588, alpha: 0.12),
            dark: UIColor(red: 0.6157, green: 0.7059, blue: 1.0, alpha: 0.16)
        )
        /// Status dot: ready, on, landed.
        static let success = adaptive(
            light: UIColor(red: 0.1804, green: 0.6078, blue: 0.4039, alpha: 1.0),
            dark: UIColor(red: 0.498, green: 0.8196, blue: 0.651, alpha: 1.0)
        )
        /// Status only.
        static let warning = adaptive(
            light: UIColor(red: 0.7216, green: 0.4627, blue: 0.0392, alpha: 1.0),
            dark: UIColor(red: 0.9608, green: 0.7216, blue: 0.2902, alpha: 1.0)
        )
        /// Status dot: off, error, recording. Destructive actions.
        static let danger = adaptive(
            light: UIColor(red: 0.7529, green: 0.2235, blue: 0.1686, alpha: 1.0),
            dark: UIColor(red: 1.0, green: 0.4196, blue: 0.3686, alpha: 1.0)
        )
        /// Hairline around a panel or card.
        static let stroke = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.06),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.1)
        )
        /// Focused or selected hairline.
        static let strokeStrong = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.14),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.16)
        )
        /// Line between rows and sections. Quieter than the panel stroke.
        static let divider = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.06),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.07)
        )
        /// 1 px inset highlight along the top edge of a panel or raised card.
        static let highlightTop = adaptive(
            light: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.9),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.05)
        )
        /// Selected row fill.
        static let selectionFill = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.055),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.09)
        )
        /// Inset ring on the selected row.
        static let selectionRing = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.06),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.06)
        )
        /// Hover feedback. Half the selection fill.
        static let hoverFill = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.03),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.045)
        )
        /// Key caps are outlined, not filled.
        static let keyCapFill = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.0),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.0)
        )
        /// 1 px outline of a key cap.
        static let keyCapStroke = adaptive(
            light: UIColor(red: 0.0, green: 0.0, blue: 0.0, alpha: 0.14),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.14)
        )
        /// Tint over the blur material of a floating panel or the pill.
        static let panelTint = adaptive(
            light: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.88),
            dark: UIColor(red: 0.102, green: 0.1059, blue: 0.1216, alpha: 0.9)
        )
        /// Opaque dark HUD for full-screen overlays (Type to Click). Same in both modes.
        static let hudFill = adaptive(
            light: UIColor(red: 0.0706, green: 0.0706, blue: 0.0784, alpha: 0.95),
            dark: UIColor(red: 0.0706, green: 0.0706, blue: 0.0784, alpha: 0.95)
        )
        /// Text on the HUD.
        static let hudText = adaptive(
            light: UIColor(red: 0.949, green: 0.949, blue: 0.9608, alpha: 1.0),
            dark: UIColor(red: 0.949, green: 0.949, blue: 0.9608, alpha: 1.0)
        )
        /// Hairline on the HUD.
        static let hudStroke = adaptive(
            light: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.1),
            dark: UIColor(red: 1.0, green: 1.0, blue: 1.0, alpha: 0.1)
        )
        /// Busy or idle marks on the HUD.
        static let hudMuted = adaptive(
            light: UIColor(red: 0.549, green: 0.5804, blue: 0.6196, alpha: 1.0),
            dark: UIColor(red: 0.549, green: 0.5804, blue: 0.6196, alpha: 1.0)
        )

        static func adaptive(light: UIColor, dark: UIColor) -> UIColor {
            UIColor { traits in
                traits.userInterfaceStyle == .dark ? dark : light
            }
        }
    }

    /// SwiftUI colours wrapping `UIColorToken`.
    enum ColorToken {
        static let surface = Color(uiColor: UIColorToken.surface)
        static let surfaceRaised = Color(uiColor: UIColorToken.surfaceRaised)
        static let surfaceSunken = Color(uiColor: UIColorToken.surfaceSunken)
        static let surfaceTint = Color(uiColor: UIColorToken.surfaceTint)
        static let well = Color(uiColor: UIColorToken.well)
        static let tileFill = Color(uiColor: UIColorToken.tileFill)
        static let tileStroke = Color(uiColor: UIColorToken.tileStroke)
        static let chipFill = Color(uiColor: UIColorToken.chipFill)
        static let textPrimary = Color(uiColor: UIColorToken.textPrimary)
        static let textSecondary = Color(uiColor: UIColorToken.textSecondary)
        static let textTertiary = Color(uiColor: UIColorToken.textTertiary)
        static let textInverse = Color(uiColor: UIColorToken.textInverse)
        static let accent = Color(uiColor: UIColorToken.accent)
        static let accentSoft = Color(uiColor: UIColorToken.accentSoft)
        static let success = Color(uiColor: UIColorToken.success)
        static let warning = Color(uiColor: UIColorToken.warning)
        static let danger = Color(uiColor: UIColorToken.danger)
        static let stroke = Color(uiColor: UIColorToken.stroke)
        static let strokeStrong = Color(uiColor: UIColorToken.strokeStrong)
        static let divider = Color(uiColor: UIColorToken.divider)
        static let highlightTop = Color(uiColor: UIColorToken.highlightTop)
        static let selectionFill = Color(uiColor: UIColorToken.selectionFill)
        static let selectionRing = Color(uiColor: UIColorToken.selectionRing)
        static let hoverFill = Color(uiColor: UIColorToken.hoverFill)
        static let keyCapFill = Color(uiColor: UIColorToken.keyCapFill)
        static let keyCapStroke = Color(uiColor: UIColorToken.keyCapStroke)
        static let panelTint = Color(uiColor: UIColorToken.panelTint)
        static let hudFill = Color(uiColor: UIColorToken.hudFill)
        static let hudText = Color(uiColor: UIColorToken.hudText)
        static let hudStroke = Color(uiColor: UIColorToken.hudStroke)
        static let hudMuted = Color(uiColor: UIColorToken.hudMuted)
    }
#endif

    /// Type scale: SF system font, fixed point sizes.
    enum TypeToken {
        static let display = Font.system(size: 28.0, weight: .semibold)
        static let title = Font.system(size: 20.0, weight: .semibold)
        static let heading = Font.system(size: 16.0, weight: .semibold)
        static let input = Font.system(size: 16.0, weight: .regular)
        static let body = Font.system(size: 14.0, weight: .regular)
        static let bodySmall = Font.system(size: 13.0, weight: .regular)
        static let label = Font.system(size: 13.0, weight: .medium)
        static let meta = Font.system(size: 12.0, weight: .regular)
        static let caption = Font.system(size: 11.0, weight: .regular)
        static let section = Font.system(size: 10.5, weight: .semibold)
        static let micro = Font.system(size: 10.0, weight: .regular)
        static let keyCap = Font.system(size: 11.0, weight: .medium)
        static let code = Font.system(size: 12.0, weight: .regular, design: .monospaced)

        /// Point sizes, for views that scale type manually.
        enum Size {
            static let display: CGFloat = 28.0
            static let title: CGFloat = 20.0
            static let heading: CGFloat = 16.0
            static let input: CGFloat = 16.0
            static let body: CGFloat = 14.0
            static let bodySmall: CGFloat = 13.0
            static let label: CGFloat = 13.0
            static let meta: CGFloat = 12.0
            static let caption: CGFloat = 11.0
            static let section: CGFloat = 10.5
            static let micro: CGFloat = 10.0
            static let keyCap: CGFloat = 11.0
            static let code: CGFloat = 12.0
        }

        /// Line height as a multiple of the size, where the scale sets one.
        enum LineHeight {
            static let body: CGFloat = 1.55
            static let bodySmall: CGFloat = 1.5
        }

        /// Letter spacing in points (em fraction times size) for tracked styles.
        enum Tracking {
            static let section: CGFloat = 0.84
        }

        /// Styles set in capitals.
        static let uppercase: Set<String> = ["section"]
    }

    /// Blur material behind `panelTint` on floating panels and the pill.
    enum Material {
        static let blur: CGFloat = 48.0
        static let saturate: CGFloat = 1.3
    }

    /// A soft black shadow: offset, blur radius, and opacity per appearance.
    struct ShadowSpec {
        let y: CGFloat
        let blur: CGFloat
        let light: Double
        let dark: Double
        /// Opacity for the given appearance.
        func opacity(dark isDark: Bool) -> Double { isDark ? dark : light }
    }

    enum Shadow {
        /// Inner of the two panel shadows.
        static let panelNear = ShadowSpec(y: 8.0, blur: 24.0, light: 0.08, dark: 0.3)
        /// Outer of the two panel shadows.
        static let panelFar = ShadowSpec(y: 40.0, blur: 80.0, light: 0.16, dark: 0.5)
        /// Drop under the selected row.
        static let selection = ShadowSpec(y: 1.0, blur: 2.0, light: 0.08, dark: 0.2)
        /// Under a raised card or composer.
        static let card = ShadowSpec(y: 2.0, blur: 8.0, light: 0.06, dark: 0.24)
    }

    /// Fixed layout widths and heights shared by the apps.
    enum Layout {
        static let panelWidth: CGFloat = 720.0
        static let answerPanelWidth: CGFloat = 800.0
        static let answerMaxWidth: CGFloat = 620.0
        static let settingsRail: CGFloat = 220.0
        static let settingsWidth: CGFloat = 760.0
        static let settingsHeight: CGFloat = 540.0
    }

    enum Radius {
        static let xs: CGFloat = 5.0
        static let sm: CGFloat = 6.0
        static let tile: CGFloat = 7.0
        static let md: CGFloat = 8.0
        static let row: CGFloat = 10.0
        static let lg: CGFloat = 12.0
        static let xl: CGFloat = 16.0
        static let pill: CGFloat = 18.0
        static let xxl: CGFloat = 24.0
    }

    enum Spacing {
        static let xxs: CGFloat = 4.0
        static let xs: CGFloat = 8.0
        static let sm: CGFloat = 12.0
        static let md: CGFloat = 16.0
        static let lg: CGFloat = 20.0
        static let xl: CGFloat = 24.0
        static let xxl: CGFloat = 32.0
        static let xxxl: CGFloat = 48.0
        static let xxxxl: CGFloat = 64.0
    }

    enum Control {
        static let statusGlyph: CGFloat = 15.0
        static let keyCap: CGFloat = 20.0
        static let tile: CGFloat = 26.0
        static let compact: CGFloat = 28.0
        static let chip: CGFloat = 28.0
        static let small: CGFloat = 32.0
        static let railRow: CGFloat = 36.0
        static let pill: CGFloat = 36.0
        static let medium: CGFloat = 40.0
        static let row: CGFloat = 40.0
        static let footer: CGFloat = 40.0
        static let large: CGFloat = 44.0
        static let sessionRow: CGFloat = 44.0
        static let xlarge: CGFloat = 48.0
        static let composer: CGFloat = 52.0
        static let hero: CGFloat = 56.0
        static let input: CGFloat = 58.0
    }

    enum Motion {
        static let hover: TimeInterval = 0.1
        static let select: TimeInterval = 0.14
        static let open: TimeInterval = 0.12
        static let fast: TimeInterval = 0.1
        static let normal: TimeInterval = 0.2
    }

    static let hairline: CGFloat = 1.0
}
