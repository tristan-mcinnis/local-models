import AppKit
import SwiftUI
import XCTest
@testable import LocalModelsBar

@MainActor
final class OperationLayoutTests: XCTestCase {
    func testHiddenPanelGrowsForFailureAndShrinksOnRetry() async {
        let model = PanelModel()
        model.override(models: [], daemonUp: true, operationState: .running(.warm, model: "test"))
        let hosting = NSHostingView(rootView: MenuBarPanelView(model: model))
        let panel = NSPanel(contentRect: NSRect(origin: .zero, size: hosting.fittingSize),
                            styleMask: [.borderless], backing: .buffered, defer: false)
        panel.contentView = hosting
        hosting.layoutSubtreeIfNeeded()
        // Let SwiftUI commit its layout without ordering
        // the native panel on screen or activating the application.
        try? await Task.sleep(nanoseconds: 100_000_000)
        let normalHeight = panel.frame.height
        model.override(models: [], daemonUp: true, operationState: .failed(.warm, model: "test",
            message: "Outcome unknown. The request timed out. Refresh before retrying."))
        hosting.layoutSubtreeIfNeeded()
        try? await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertGreaterThan(panel.frame.height, normalHeight)
        XCTAssertGreaterThanOrEqual(panel.frame.height, hosting.fittingSize.height - 1)
        XCTAssertFalse(panel.isVisible)
        model.override(models: [], daemonUp: true, operationState: .running(.warm, model: "test"))
        hosting.layoutSubtreeIfNeeded()
        try? await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(panel.frame.height, normalHeight, accuracy: 1)
        XCTAssertFalse(panel.isVisible)
    }
}
