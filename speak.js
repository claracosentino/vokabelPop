// Pronuncia tedesca con la voce di Windows (condivisa da banner e finestra di controllo).
function speakDe(text) {
  if (!text || !window.speechSynthesis) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'de-DE';
  u.rate = 0.85;
  const v = speechSynthesis.getVoices().find(v => v.lang.startsWith('de'));
  if (v) u.voice = v;
  speechSynthesis.speak(u);
}
