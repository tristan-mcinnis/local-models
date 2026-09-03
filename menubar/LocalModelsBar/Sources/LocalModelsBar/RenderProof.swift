import AppKit
import SwiftUI

// Offscreen render proof. `LocalModelsBar --render-proof <dir>` draws every
// Slate surface into PNGs without putting a window on screen, so the design can
// be compared against design-system/DESIGN.md and against Memory's panel by
// hand or in CI. Nothing here runs in the normal app path, and nothing here
// touches the daemon: every state is a fixed snapshot, so the proof is the same
// on any Mac whether or not the daemon happens to be up. Ported from
// memory-menubar/Sources/MemoryBar/RenderProof.swift.

@MainActor
enum RenderProof {

    /// Render every proof surface into `directory` and return the file paths.
    @discardableResult
    static func run(into directory: URL) -> [URL] {
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

        var written: [URL] = []
        for (name, appearance) in [("dark", NSAppearance(named: .darkAqua)), ("light", NSAppearance(named: .aqua))] {
            let panels: [(String, PanelModel)] = [
                ("panel-running", runningModel()),
                ("panel-down", downModel()),
            ]
            for (surface, model) in panels {
                if let url = write(
                    view: MenuBarPanelView(model: model),
                    size: NSSize(width: MenuBarPanelView.width + 2 * House.Spacing.md, height: 320),
                    appearance: appearance,
                    to: directory.appendingPathComponent("\(surface)-\(name).png"),
                    fitToContent: true
                ) {
                    written.append(url)
                }
            }
            if let url = write(
                view: SettingsView(model: runningModel()),
                size: NSSize(width: 760, height: 620),
                appearance: appearance,
                to: directory.appendingPathComponent("settings-\(name).png")
            ) {
                written.append(url)
            }
        }
        return written
    }

    // MARK: - The states

    /// Three registered models, one of them warm. Decoded from the daemon's
    /// own `GET /v1/models` shape rather than built in Swift, so the proof
    /// draws what the app would actually get back.
    private static let registry: [ModelRow] = {
        let json = """
        {"models":[
          {"id":"qwen3-vl","backend":"mlx-vlm","capabilities":["text","image","vision"],
           "warm":true,"backend_available":true},
          {"id":"gemma-completion","backend":"llama-gguf","capabilities":["completion"],
           "warm":false,"backend_available":true},
          {"id":"parakeet-stt","backend":"mlx-audio","capabilities":["audio"],
           "warm":false,"backend_available":true}]}
        """
        // The proof is a fixed picture; a payload that will not decode is a bug
        // in this file, not a runtime condition, so it fails loudly.
        return try! JSONDecoder().decode(ModelList.self, from: Data(json.utf8)).models
    }()

    static func runningModel() -> PanelModel {
        let model = PanelModel()
        model.override(models: registry, daemonUp: true)
        model.selection = 0
        return model
    }

    static func downModel() -> PanelModel {
        let model = PanelModel()
        model.override(models: [], daemonUp: false)
        model.selection = 0
        return model
    }

    // MARK: - Rendering

    private static func write<V: View>(
        view: V,
        size: NSSize,
        appearance: NSAppearance?,
        to url: URL,
        fitToContent: Bool = false
    ) -> URL? {
        let hosting = NSHostingView(rootView: view)
        hosting.appearance = appearance
        hosting.frame = NSRect(origin: .zero, size: size)
        if fitToContent {
            let fitted = hosting.fittingSize
            hosting.frame = NSRect(
                origin: .zero,
                size: NSSize(width: max(fitted.width, size.width), height: max(fitted.height, 1))
            )
        }
        hosting.layoutSubtreeIfNeeded()
        // Give SwiftUI one runloop turn to commit its first layout pass.
        RunLoop.main.run(until: Date().addingTimeInterval(0.35))
        hosting.layoutSubtreeIfNeeded()
        return capture(hosting, appearance: appearance, to: url)
    }

    /// Snapshot a view over a plain ground, so a glass panel reads the way it
    /// does on screen instead of over transparency.
    private static func capture(_ view: NSView, appearance: NSAppearance?, to url: URL) -> URL? {
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return nil }
        view.cacheDisplay(in: view.bounds, to: rep)

        let scale = rep.pixelsWide > 0 ? CGFloat(rep.pixelsWide) / view.bounds.width : 1
        guard let composite = NSBitmapImageRep(
            bitmapDataPlanes: nil,
            pixelsWide: rep.pixelsWide,
            pixelsHigh: rep.pixelsHigh,
            bitsPerSample: 8,
            samplesPerPixel: 4,
            hasAlpha: true,
            isPlanar: false,
            colorSpaceName: .deviceRGB,
            bytesPerRow: 0,
            bitsPerPixel: 0
        ) else { return nil }

        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: composite)
        NSGraphicsContext.current?.cgContext.scaleBy(x: scale, y: scale)
        let isDark = (appearance ?? NSAppearance.currentDrawing())
            .bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
        (appearance ?? NSAppearance.currentDrawing()).performAsCurrentDrawingAppearance {
            (isDark ? NSColor(white: 0.09, alpha: 1) : NSColor(white: 0.86, alpha: 1)).setFill()
            NSRect(origin: .zero, size: view.bounds.size).fill()
        }
        NSImage(size: view.bounds.size, flipped: false) { rect in
            rep.draw(in: rect)
            return true
        }.draw(in: NSRect(origin: .zero, size: view.bounds.size))
        NSGraphicsContext.restoreGraphicsState()

        guard let data = composite.representation(using: .png, properties: [:]) else { return nil }
        try? data.write(to: url)
        return url
    }
}
