import XCTest
@testable import LocalModelsBar

/// The row the panel draws from `GET /v1/models`: what it decodes, and the one
/// line of text it puts under the model id.
final class ModelRowTests: XCTestCase {

    private func rows(_ json: String) throws -> [ModelRow] {
        try JSONDecoder().decode(ModelList.self, from: Data(json.utf8)).models
    }

    func testWarmRowShowsCapabilitiesAndIdleTime() throws {
        let row = try XCTUnwrap(rows("""
        {"models":[{"id":"gemma","backend":"llama-gguf","capabilities":["completion"],
          "warm":true,"backend_available":true,"idle_seconds":740}]}
        """).first)
        XCTAssertEqual(row.idleLabel, "idle 12m")
        XCTAssertEqual(row.detail, "completion · idle 12m")
    }

    func testIdleReadsInHoursOnceItPassesOne() throws {
        let row = try XCTUnwrap(rows("""
        {"models":[{"id":"gemma","backend":"llama-gguf","capabilities":["completion"],
          "warm":true,"backend_available":true,"idle_seconds":7200}]}
        """).first)
        XCTAssertEqual(row.idleLabel, "idle 2h")
    }

    func testFreshUseReadsAsUnderAMinute() throws {
        let row = try XCTUnwrap(rows("""
        {"models":[{"id":"gemma","backend":"llama-gguf","capabilities":["completion"],
          "warm":true,"backend_available":true,"idle_seconds":3}]}
        """).first)
        XCTAssertEqual(row.idleLabel, "idle <1m")
    }

    func testColdRowNeverShowsAnIdleTime() throws {
        let row = try XCTUnwrap(rows("""
        {"models":[{"id":"gemma","backend":"llama-gguf","capabilities":["completion"],
          "warm":false,"backend_available":true,"idle_seconds":9000}]}
        """).first)
        XCTAssertNil(row.idleLabel)
        XCTAssertEqual(row.detail, "completion")
    }

    func testNullIdleShowsNothing() throws {
        let row = try XCTUnwrap(rows("""
        {"models":[{"id":"gemma","backend":"llama-gguf","capabilities":["completion"],
          "warm":true,"backend_available":true,"idle_seconds":null}]}
        """).first)
        XCTAssertNil(row.idleLabel)
        XCTAssertEqual(row.detail, "completion")
    }

    /// A daemon that predates idle unloading sends no field at all; the panel
    /// draws the row it always drew.
    func testARowWithoutTheFieldStillDecodes() throws {
        let row = try XCTUnwrap(rows("""
        {"models":[{"id":"qwen3-vl","backend":"mlx-vlm","capabilities":["text","vision"],
          "warm":true,"backend_available":true}]}
        """).first)
        XCTAssertNil(row.idleSeconds)
        XCTAssertEqual(row.detail, "text · vision")
    }
}
