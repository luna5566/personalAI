import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:speech_to_text/speech_to_text.dart';

final speechInputServiceProvider = Provider<SpeechInputService>((ref) {
  return SpeechInputService();
});

class SpeechInputService {
  SpeechInputService({SpeechToText? speech})
      : _speech = speech ?? SpeechToText();

  final SpeechToText _speech;
  bool _initialized = false;

  Future<bool> start({
    required void Function(String text) onText,
    required void Function() onStopped,
    required void Function(String message) onError,
  }) async {
    final available = await _speech.initialize(
      onStatus: (status) {
        if (status == 'done' || status == 'notListening') {
          onStopped();
        }
      },
      onError: (error) => onError(error.errorMsg),
    );
    if (!available) {
      return false;
    }
    _initialized = true;
    await _speech.listen(
      onResult: (result) => onText(result.recognizedWords),
      listenOptions: SpeechListenOptions(
        partialResults: true,
        cancelOnError: true,
      ),
    );
    return true;
  }

  Future<void> stop() async {
    if (_initialized) {
      await _speech.stop();
    }
  }
}
