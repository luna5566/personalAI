import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/core/network/cache_state.dart';

void main() {
  test('clears the warning only after every request returns live data',
      () async {
    var fullyRevalidatedCount = 0;
    final container = ProviderContainer(
      overrides: [
        cacheRevalidationTrackerProvider.overrideWith(
          () => CacheRevalidationTracker(
            onFullyRevalidated: () => fullyRevalidatedCount += 1,
            settleDelay: Duration.zero,
          ),
        ),
      ],
    );
    addTearDown(container.dispose);
    final tracker = container.read(cacheRevalidationTrackerProvider.notifier);
    CacheRevalidationState state() =>
        container.read(cacheRevalidationTrackerProvider);

    final generation = tracker.start();
    expect(tracker.requestStarted(), generation);
    expect(tracker.requestStarted(), generation);

    tracker.requestSucceeded(generation);
    expect(state().inProgress, isTrue);
    tracker.requestSucceeded(generation);
    await Future<void>.delayed(Duration.zero);

    expect(state().inProgress, isFalse);
    expect(state().registeredRequests, 2);
    expect(state().liveResponses, 2);
    expect(fullyRevalidatedCount, 1);
  });

  test('keeps the warning when one response falls back to cache', () async {
    var fullyRevalidatedCount = 0;
    final container = ProviderContainer(
      overrides: [
        cacheRevalidationTrackerProvider.overrideWith(
          () => CacheRevalidationTracker(
            onFullyRevalidated: () => fullyRevalidatedCount += 1,
            settleDelay: Duration.zero,
          ),
        ),
      ],
    );
    addTearDown(container.dispose);
    final tracker = container.read(cacheRevalidationTrackerProvider.notifier);
    CacheRevalidationState state() =>
        container.read(cacheRevalidationTrackerProvider);

    final generation = tracker.start();
    tracker.requestStarted();
    tracker.requestStarted();

    tracker.requestUsedFallback(generation);
    tracker.requestSucceeded(generation);
    await Future<void>.delayed(Duration.zero);

    expect(state().inProgress, isFalse);
    expect(state().liveResponses, 1);
    expect(state().fallbackResponses, 1);
    expect(fullyRevalidatedCount, 0);
  });

  test('ignores late results from an older generation', () async {
    final container = ProviderContainer(
      overrides: [
        cacheRevalidationTrackerProvider.overrideWith(
          () => CacheRevalidationTracker(settleDelay: Duration.zero),
        ),
      ],
    );
    addTearDown(container.dispose);
    final tracker = container.read(cacheRevalidationTrackerProvider.notifier);
    CacheRevalidationState state() =>
        container.read(cacheRevalidationTrackerProvider);

    final oldGeneration = tracker.start();
    tracker.requestStarted();
    final newGeneration = tracker.start();
    tracker.requestStarted();

    tracker.requestSucceeded(oldGeneration);

    expect(state().generation, newGeneration);
    expect(state().activeRequests, 1);
    expect(state().liveResponses, 0);
  });
}
