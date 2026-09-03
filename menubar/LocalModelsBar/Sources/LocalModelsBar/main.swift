import AppKit

// Menu-bar entry point. The app is `.accessory`: no Dock icon, and it never
// takes the foreground unless a row asks for it.
//
// Top-level code runs on the main thread; telling the compiler so lets the
// @MainActor AppDelegate be built without an implicit async hop.
MainActor.assumeIsolated {
    let app = NSApplication.shared

    // Offscreen render proof: draw the Slate surfaces to PNGs and exit without
    // ever showing a window.
    if let index = CommandLine.arguments.firstIndex(of: "--render-proof"),
       CommandLine.arguments.count > index + 1 {
        app.setActivationPolicy(.prohibited)
        let directory = URL(fileURLWithPath: CommandLine.arguments[index + 1])
        for url in RenderProof.run(into: directory) {
            print(url.path)
        }
        exit(0)
    }

    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.accessory)
    app.run()
}
