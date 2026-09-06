class MediaCapabilities {
  const MediaCapabilities({
    required this.ocrEnabled,
    required this.speechToTextEnabled,
  });

  final bool ocrEnabled;
  final bool speechToTextEnabled;

  factory MediaCapabilities.fromJson(Map<String, dynamic> json) {
    final ocr = json['ocr'];
    final speech = json['speech_to_text'];
    return MediaCapabilities(
      ocrEnabled: ocr is Map<String, dynamic>
          ? ocr['enabled'] == true
          : false,
      speechToTextEnabled: speech is Map<String, dynamic>
          ? speech['enabled'] == true
          : false,
    );
  }

  static const fallback = MediaCapabilities(
    ocrEnabled: false,
    speechToTextEnabled: false,
  );
}
