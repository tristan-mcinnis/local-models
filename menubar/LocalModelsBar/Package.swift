// swift-tools-version:5.10
import PackageDescription

// Local Models — the menu-bar face of the local-models daemon on this Mac. The
// app drives a program it does not own: the daemon's launchd job and its HTTP
// registry. It stores nothing of its own.
let package = Package(
    name: "LocalModelsBar",
    // The Slate menu-bar kit (HouseUI, MenuBarPanel) is shared with Cotype and
    // Memory, which are macOS 14 apps.
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "LocalModelsBar"),
        // The app's own window rules: the menu bar a normal window gets, and
        // when the app goes back to being a menu-bar app. AppKit only, no
        // window is opened.
        .testTarget(name: "LocalModelsBarTests", dependencies: ["LocalModelsBar"])
    ]
)
