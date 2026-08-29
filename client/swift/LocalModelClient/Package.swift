// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "LocalModelClient",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "LocalModelClient", targets: ["LocalModelClient"])
    ],
    targets: [
        .target(name: "LocalModelClient")
    ]
)
