// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "FinanceCockpit",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(
            name: "FinanceCockpit",
            targets: ["FinanceCockpit"]
        )
    ],
    dependencies: [],
    targets: [
        .executableTarget(
            name: "FinanceCockpit",
            dependencies: [],
            path: "Sources/ETFCockpit",
            linkerSettings: [
                .linkedLibrary("sqlite3")
            ]
        ),
        .testTarget(
            name: "ETFCockpitTests",
            dependencies: ["FinanceCockpit"],
            path: "Tests/ETFCockpitTests",
            linkerSettings: [
                .linkedLibrary("sqlite3")
            ]
        )
    ]
)
