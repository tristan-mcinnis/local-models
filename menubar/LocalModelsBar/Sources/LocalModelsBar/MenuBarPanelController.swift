import AppKit
import HouseUIKit

extension PanelModel: MenuPanelModeling {}

/// Local Models' panel window. Return warms the selected model and ⌘Return
/// unloads it.
@MainActor
final class MenuBarPanelController: MenuPanelController<MenuBarPanelView, PanelModel> {
    init(model: PanelModel) {
        super.init(model: model, width: MenuBarPanelView.width, rootView: { MenuBarPanelView(model: model) })
    }

    override func panelWillShow() {
        model.selection = 0
        model.panelOpened()
    }

    override func panelDidClose() {
        model.isPanelOpen = false
    }

    /// The command chords are handled here rather than as SwiftUI shortcuts so
    /// they fire wherever focus sits inside the panel.
    override func handle(_ key: PanelKeyPress) -> Bool {
        if key.flags.contains(.command) {
            if key.keyCode == 36 || key.keyCode == 76 {
                model.unloadSelection()
                return true
            }
            switch key.characters?.lowercased() {
            case "r": model.poll(); return true
            case ",": model.onOpenSettings(); return true
            case "q": model.onQuit(); return true
            default: return false
            }
        }
        return super.handle(key)
    }
}
