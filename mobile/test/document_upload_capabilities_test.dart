import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/documents/widgets/document_upload_flow.dart';
import 'package:personal_ai_mobile/features/settings/models/media_capabilities.dart';

void main() {
  test('media capabilities parse enabled flags', () {
    final capabilities = MediaCapabilities.fromJson({
      'ocr': {'provider': 'openai_compatible', 'enabled': true},
      'speech_to_text': {'provider': 'disabled', 'enabled': false},
    });
    expect(capabilities.ocrEnabled, isTrue);
    expect(capabilities.speechToTextEnabled, isFalse);
  });

  test('upload extensions exclude media when providers disabled', () {
    final extensions = allowedUploadExtensions(MediaCapabilities.fallback);
    expect(extensions, containsAll(['txt', 'md', 'markdown', 'pdf']));
    expect(extensions, isNot(contains('png')));
    expect(extensions, isNot(contains('mp3')));
  });

  test('upload extensions include media when providers enabled', () {
    const capabilities = MediaCapabilities(
      ocrEnabled: true,
      speechToTextEnabled: true,
    );
    final extensions = allowedUploadExtensions(capabilities);
    expect(extensions, contains('png'));
    expect(extensions, contains('jpg'));
    expect(extensions, contains('mp3'));
    expect(extensions, contains('wav'));
  });

  test('filename helpers detect image and audio uploads', () {
    expect(isImageUploadFilename('scan.PNG'), isTrue);
    expect(isImageUploadFilename('notes.txt'), isFalse);
    expect(isAudioUploadFilename('voice.m4a'), isTrue);
    expect(isAudioUploadFilename('doc.pdf'), isFalse);
  });
}
