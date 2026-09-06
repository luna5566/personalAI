import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/core/network/cache_state.dart';

void main() {
  test('clears the warning only after every request returns live data',
      () async {
    var fullyRevalidatedCount = 0;
    final tracker = CacheRevalidationTracker(
      () => fullyRevalidatedCount += 1,
      settleDelay: Duration.zero,
    );
    addTearDown(tracker.dispose);

    final generation = tracker.start();
    expect(tracker.requestStarted(), generation);
    expect(tracker.requestStarted(), generation);

    tracker.requestSucceeded(generation);
    expect(tracker.state.inProgress, isTrue);
    tracker.requestSucceeded(generation);
    await Future<void>.delayed(Duration.zero);

    expect(tracker.state.inProgress, isFalse);
    expect(tracker.state.registeredRequests, 2);
    expect(tracker.state.liveResponses, 2);
    expect(fullyRevalidatedCount, 1);
  });

  test('keeps the warning when one response falls back to cache', () async {
    var fullyRevalidatedCount = 0;
    final tracker = CacheRevalidationTracker(
      () => fullyRevalidatedCount += 1,
      settleDelay: Duration.zero,
    );
    addTearDown(tracker.dispose);

    final generation = tracker.start();
    tracker.requestStarted();
    tracker.requestStarted();

    tracker.requestUsedFallback(generation);
    tracker.requestSucceeded(generation);
    await Future<void>.delayed(Duration.zero);

    expect(tracker.state.inProgress, isFalse);
    expect(tracker.state.liveResponses, 1);
    expect(tracker.state.fallbackResponses, 1);
    expect(fullyRevalidatedCount, 0);
  });

  test('ignores late results from an older generation', () async {
    final tracker = CacheRevalidationTracker(
      () {},
      settleDelay: Duration.zero,
    );
    addTearDown(tracker.dispose);

    final oldGeneration = tracker.start();
    tracker.requestStarted();
    final newGeneration = tracker.start();
    tracker.requestStarted();

    tracker.requestSucceeded(oldGeneration);

    expect(tracker.state.generation, newGeneration);
    expect(tracker.state.activeRequests, 1);
    expect(tracker.state.liveResponses, 0);
  });
}
