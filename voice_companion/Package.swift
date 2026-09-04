// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "HiVoice",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "HiVoice",
            path: "Sources/HiVoice"
        )
    ]
)
