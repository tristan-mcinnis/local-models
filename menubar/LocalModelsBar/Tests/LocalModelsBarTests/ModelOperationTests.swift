import XCTest
@testable import LocalModelsBar

@MainActor
final class ModelOperationTests: XCTestCase {
    private func response(_ request: URLRequest, _ status: Int = 200, _ body: String = "{}") -> (Data, URLResponse) {
        (Data(body.utf8), HTTPURLResponse(url: request.url!, statusCode: status,
                                        httpVersion: nil, headerFields: nil)!)
    }

    func testWarmSuccessReconcilesResidencyAndReturnsIdle() async {
        var routes: [String] = []
        let model = PanelModel(transport: { request in
            routes.append(request.url!.path)
            if request.httpMethod == "POST" { return self.response(request) }
            return self.response(request, 200, """
            {"models":[{"id":"test","backend":"test","capabilities":[],
            "warm":true,"backend_available":true}]}
            """)
        })
        await model.warm("test")
        XCTAssertEqual(routes, ["/v1/warm", "/v1/models"])
        XCTAssertEqual(model.operationState, .idle)
        XCTAssertEqual(model.models.first?.warm, true)
    }

    func testHTTPFailureRetainsHintThroughRefreshAndClearsOnSuccessfulRetry() async {
        var fail = true
        let model = PanelModel(transport: { request in
            if request.httpMethod == "GET" { return self.response(request, 200, "{\"models\":[]}") }
            return fail ? self.response(request, 502, "{\"error\":\"Not ready\",\"hint\":\"Start backend.\"}")
                : self.response(request)
        })
        await model.warm("test")
        XCTAssertEqual(model.operationState, .failed(.warm, model: "test", message: "Not ready Start backend."))
        await model.refresh()
        XCTAssertTrue(model.operationState.failure!.contains("Start backend."))
        fail = false
        await model.warm("test")
        XCTAssertEqual(model.operationState, .idle)
    }

    func testTransportTimeoutHasUnknownOutcomeAndCanRetry() async {
        var fail = true
        let model = PanelModel(transport: { request in
            if request.httpMethod == "POST", fail { throw URLError(.timedOut) }
            return self.response(request, 200, "{\"models\":[]}")
        })
        await model.unload("test")
        XCTAssertTrue(model.operationState.failure!.contains("Outcome unknown"))
        XCTAssertNil(model.busy)
        fail = false
        await model.unload("test")
        XCTAssertEqual(model.operationState, .idle)
    }

    func testCancellationReleasesAdmissionAndKeepsUnknownOutcome() async {
        let model = PanelModel(transport: { _ in throw CancellationError() })
        await model.warm("test")
        XCTAssertNil(model.busy)
        XCTAssertTrue(model.operationState.failure!.contains("Outcome unknown"))
    }

    func testCancellingSuspendedWaitDoesNotClaimDaemonCancellationAndAllowsRetry() async {
        var finish: CheckedContinuation<Void, Never>?
        let entered = expectation(description: "wait started")
        var suspend = true
        let model = PanelModel(transport: { request in
            if request.httpMethod == "POST", suspend {
                await withCheckedContinuation { continuation in
                    finish = continuation
                    entered.fulfill()
                }
                try Task.checkCancellation()
            }
            return self.response(request, 200, "{\"models\":[]}")
        })
        await withTaskGroup(of: Void.self) { group in
            group.addTask { await model.warm("test") }
            await fulfillment(of: [entered], timeout: 2)
            group.cancelAll()
            finish?.resume()
        }
        XCTAssertNil(model.busy)
        XCTAssertTrue(model.operationState.failure!.contains("Outcome unknown"))
        suspend = false
        await model.warm("test")
        XCTAssertEqual(model.operationState, .idle)
    }

    func testDuplicateActionsAreRejectedWhileRequestIsSuspended() async {
        var posts = 0
        var finish: CheckedContinuation<Void, Never>?
        let entered = expectation(description: "POST suspended")
        let model = PanelModel(transport: { request in
            if request.httpMethod == "POST" {
                posts += 1
                await withCheckedContinuation { continuation in
                    finish = continuation
                    entered.fulfill()
                }
            }
            return self.response(request, 200, "{\"models\":[]}")
        })
        await withTaskGroup(of: Void.self) { group in
            group.addTask { await model.unload("first") }
            await fulfillment(of: [entered], timeout: 2)
            XCTAssertEqual(model.operationState, .running(.unload, model: "first"))
            XCTAssertEqual(model.operationState.progress(for: "first"), "Unloading…")
            XCTAssertNil(model.operationState.progress(for: "second"))
            await model.warm("second")
            await model.unload("first")
            XCTAssertEqual(posts, 1)
            finish?.resume()
        }
        XCTAssertEqual(model.operationState, .idle)
    }

    func testUnexpectedHTTPErrorStillOffersRecovery() async {
        let model = PanelModel(transport: { request in
            if request.httpMethod == "POST" { return self.response(request, 503, "unavailable") }
            return self.response(request, 200, "{\"models\":[]}")
        })
        await model.unload("test")
        XCTAssertTrue(model.operationState.failure!.contains("HTTP 503"))
        XCTAssertTrue(model.operationState.failure!.contains("retry"))
    }
}
