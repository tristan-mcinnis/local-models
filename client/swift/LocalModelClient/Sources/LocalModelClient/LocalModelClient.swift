import Foundation

/// Thin client for the local-models daemon.
///
/// Apps use this instead of embedding a model runtime: the daemon keeps the
/// models warm, the app makes a localhost call. New capability on the daemon,
/// new method here, nothing else changes in the app.
public struct LocalModelClient {
    public struct ModelInfo: Decodable {
        public let id: String
        public let backend: String
        public let capabilities: [String]
        public let warm: Bool
        public let backendAvailable: Bool

        enum CodingKeys: String, CodingKey {
            case id, backend, capabilities, warm
            case backendAvailable = "backend_available"
        }
    }

    public struct ModelList: Decodable {
        public let `default`: String?
        public let models: [ModelInfo]
    }

    public struct TextResult: Decodable {
        public let model: String
        public let text: String
    }

    public enum ClientError: Error {
        case badResponse(status: Int, body: String)
        case notImplemented(String)
    }

    public let baseURL: URL
    private let session: URLSession

    public init(baseURL: URL = URL(string: "http://127.0.0.1:8078")!, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    public func health() async throws -> Bool {
        let (_, response) = try await session.data(from: baseURL.appendingPathComponent("health"))
        return (response as? HTTPURLResponse)?.statusCode == 200
    }

    public func models() async throws -> ModelList {
        let (data, _) = try await session.data(from: baseURL.appendingPathComponent("v1/models"))
        return try JSONDecoder().decode(ModelList.self, from: data)
    }

    public func vision(imagePNG: Data, prompt: String, model: String? = nil) async throws -> TextResult {
        var body: [String: Any] = ["prompt": prompt, "image_b64": imagePNG.base64EncodedString()]
        if let model { body["model"] = model }
        return try await post(path: "v1/vision", body: body)
    }

    public func ask(prompt: String, model: String? = nil, maxTokens: Int = 256) async throws -> TextResult {
        var body: [String: Any] = ["prompt": prompt, "max_tokens": maxTokens]
        if let model { body["model"] = model }
        return try await post(path: "v1/ask", body: body)
    }

    private func post(path: String, body: [String: Any]) async throws -> TextResult {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else {
            let text = String(data: data, encoding: .utf8) ?? ""
            if status == 501 { throw ClientError.notImplemented(text) }
            throw ClientError.badResponse(status: status, body: text)
        }
        return try JSONDecoder().decode(TextResult.self, from: data)
    }
}
