import Foundation
import XCTest
@testable import LocalModelClient

/// Answers every request with one canned reply, so the client is tested
/// without a daemon.
final class StubProtocol: URLProtocol {
    nonisolated(unsafe) static var status = 200
    nonisolated(unsafe) static var body = Data()

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let response = HTTPURLResponse(url: request.url!, statusCode: Self.status,
                                       httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Self.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

final class StatusTests: XCTestCase {
    private func client(status: Int, body: String) -> LocalModelClient {
        StubProtocol.status = status
        StubProtocol.body = Data(body.utf8)
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubProtocol.self]
        return LocalModelClient(session: URLSession(configuration: config))
    }

    /// Before the fix, models() decoded the error envelope as a ModelList and
    /// threw a DecodingError that hid the daemon's message.
    func testModelsErrorReplyIsBadResponseNotDecodeError() async {
        let c = client(status: 502, body: #"{"error": "registry unreadable"}"#)
        do {
            _ = try await c.models()
            XCTFail("a 502 was decoded as a model list")
        } catch LocalModelClient.ClientError.badResponse(let status, let body) {
            XCTAssertEqual(status, 502)
            XCTAssertTrue(body.contains("registry unreadable"))
        } catch {
            XCTFail("expected badResponse, got \(error)")
        }
    }

    func testModelsSuccessDecodes() async throws {
        let c = client(status: 200, body: #"""
        {"default": "fake", "models": [{"id": "fake", "backend": "mlx-vlm",
         "capabilities": ["vision"], "warm": false, "backend_available": true}]}
        """#)
        let list = try await c.models()
        XCTAssertEqual(list.default, "fake")
        XCTAssertEqual(list.models.map(\.id), ["fake"])
    }

    func testPlannedCapabilityIsNotImplemented() async {
        let c = client(status: 501, body: #"{"error": "phase 2"}"#)
        do {
            _ = try await c.ask(prompt: "hi")
            XCTFail("a 501 was decoded as a result")
        } catch LocalModelClient.ClientError.notImplemented(let body) {
            XCTAssertTrue(body.contains("phase 2"))
        } catch {
            XCTFail("expected notImplemented, got \(error)")
        }
    }
}
