// swift-tools-version:5.10
import PackageDescription

// Local Models — the menu-bar face of the local-models daemon on this Mac. The
// app drives a program it does not own: the daemon's launchd job and its HTTP
// registry. It stores nothing of its own.
let package = Package(
    name: "LocalModelsBar",
    // The Slate menu-bar kit (HouseUIKit) is shared with Cotype, Memory and
    // Usage, which are macOS 14 apps.
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/tristan-mcinnis/design-system", from: "1.0.0"),
    ],
    targets: [
        .executableTarget(
            name: "LocalModelsBar",
            dependencies: [
                .product(name: "HouseDesign", package: "design-system"),
                .product(name: "HouseUIKit", package: "design-system"),
            ]
        ),
        // The app's own window rules: the menu bar a normal window gets, and
        // when the app goes back to being a menu-bar app. AppKit only, no
        // window is opened.
        .testTarget(
            name: "LocalModelsBarTests",
            dependencies: [
                "LocalModelsBar",
                .product(name: "HouseDesign", package: "design-system"),
                .product(name: "HouseUIKit", package: "design-system"),
            ]
        )
    ]
)
