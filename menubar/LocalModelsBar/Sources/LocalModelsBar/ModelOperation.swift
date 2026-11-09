import Foundation

/// A command receipt is separate from the daemon's current model residency.
enum ModelOperation: String, Equatable {
    case warm, unload

    var progress: String { self == .warm ? "Warming…" : "Unloading…" }
    var title: String { self == .warm ? "Warm" : "Unload" }
}

enum ModelOperationState: Equatable {
    case idle
    case running(ModelOperation, model: String)
    case failed(ModelOperation, model: String, message: String)

    var busyModel: String? {
        if case .running(_, let model) = self { return model }
        return nil
    }

    var failure: String? {
        if case .failed(let operation, let model, let message) = self {
            return "\(operation.title) \(model): \(message)"
        }
        return nil
    }

    func progress(for model: String) -> String? {
        if case .running(let operation, let id) = self, id == model {
            return operation.progress
        }
        return nil
    }
}

/// Network I/O stays off the UI's actor; tests replace the async call itself.
actor PanelHTTPClient {
    static let shared = PanelHTTPClient()

    func send(_ request: URLRequest) async throws -> (Data, URLResponse) {
        try await URLSession.shared.data(for: request)
    }
}

struct DaemonCommandError: Decodable {
    let error: String
    let hint: String?

    var message: String { [error, hint].compactMap { $0 }.joined(separator: " ") }
}
