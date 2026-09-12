import XCTest
@testable import LocalModelsBar

/// The idle backoff: what the poll interval becomes when nobody opens the
/// panel, what opening it does, and the tolerance the timer carries. The
/// decision is a pure function of the configured interval and the idle time,
/// so nothing here waits on a clock, and no test here calls the daemon.
@MainActor
final class PollBackoffTests: XCTestCase {

    private var refreshCount = 0

    private func makeModel(now: @escaping () -> Date = { Date() }) -> PanelModel {
        let model = PanelModel(
            defaults: UserDefaults(suiteName: "PollBackoffTests-\(UUID().uuidString)")!
        )
        model.now = now
        // Opening a panel must never call the daemon in a test.
        model.backgroundRefresh = { [weak self] in self?.refreshCount += 1 }
        return model
    }

    // MARK: - The pure decision

    func testTheConfiguredIntervalStandsUntilTheIdleThreshold() {
        XCTAssertEqual(PanelModel.backedOffInterval(base: 60, idleFor: 0), 60)
        XCTAssertEqual(PanelModel.backedOffInterval(base: 60, idleFor: 60 * 60), 60)
    }

    func testTheIntervalDoublesForEveryIdleThresholdPassed() {
        XCTAssertEqual(PanelModel.backedOffInterval(base: 60, idleFor: PanelModel.idleThreshold), 120)
        XCTAssertEqual(PanelModel.backedOffInterval(base: 60, idleFor: 2 * PanelModel.idleThreshold), 240)
    }

    func testTheIntervalStopsAtTheCeiling() {
        XCTAssertEqual(
            PanelModel.backedOffInterval(base: 60, idleFor: 48 * 60 * 60),
            PanelModel.idlePollCeiling
        )
    }

    /// A configured interval longer than the ceiling is the user's choice, so
    /// the backoff must never shorten it.
    func testAConfiguredIntervalPastTheCeilingIsNeverShortened() {
        XCTAssertEqual(PanelModel.backedOffInterval(base: 3600, idleFor: 48 * 60 * 60), 3600)
    }

    func testAnUnpolledRegistryCountsAsStale() {
        XCTAssertTrue(PanelModel.isStale(age: nil, base: 60))
    }

    func testAReadingOlderThanOnePollCountsAsStale() {
        XCTAssertFalse(PanelModel.isStale(age: 59, base: 60))
        XCTAssertTrue(PanelModel.isStale(age: 61, base: 60))
    }

    // MARK: - The model

    func testALongUnopenedPanelLengthensTheInterval() {
        let launch = Date()
        let model = makeModel(now: { launch.addingTimeInterval(48 * 60 * 60) })
        XCTAssertEqual(model.pollInterval, PanelModel.idlePollCeiling)
    }

    func testOpeningThePanelRestoresTheNormalCadence() {
        let launch = Date()
        let model = makeModel(now: { launch.addingTimeInterval(48 * 60 * 60) })
        XCTAssertEqual(model.pollInterval, PanelModel.idlePollCeiling)

        model.panelOpened()
        XCTAssertEqual(model.pollInterval, PanelModel.openPollInterval)

        // Closed again, and the idle clock starts from this open, not launch.
        model.isPanelOpen = false
        XCTAssertEqual(model.pollInterval, model.baseInterval)
    }

    func testTheTimerCarriesTolerance() throws {
        let model = makeModel()
        model.schedulePoll()
        let scheduled = try XCTUnwrap(model.scheduledPoll)
        XCTAssertEqual(scheduled.interval, model.pollInterval, accuracy: 0.001)
        XCTAssertEqual(
            scheduled.tolerance,
            model.pollInterval * PanelModel.pollToleranceFraction,
            accuracy: 0.001
        )
        XCTAssertGreaterThan(scheduled.tolerance, 0)
    }

    func testOpeningAStalePanelKicksABackgroundRefresh() {
        let model = makeModel()
        model.lastPolledAt = Date(timeIntervalSinceNow: -3600)
        model.panelOpened()
        XCTAssertEqual(refreshCount, 1)
    }

    /// A panel that has never polled has nothing on screen to trust, so an
    /// open reads.
    func testOpeningAnUnpolledPanelKicksABackgroundRefresh() {
        let model = makeModel()
        model.panelOpened()
        XCTAssertEqual(refreshCount, 1)
    }

    func testOpeningAFreshPanelReadsNothing() {
        let model = makeModel()
        model.lastPolledAt = Date()
        model.panelOpened()
        XCTAssertEqual(refreshCount, 0)
    }
}
