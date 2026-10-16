import requests
import json
import logging

logger = logging.getLogger("GeminiAnalyzer")


class GeminiAnalyzer:
    """
    Gemini Yapay Zeka modellerini (2.5-flash-lite, flash-lite-latest, 2.5-flash) kullanarak 
    iş ve memur ilanlarını analiz eden, kota aşımında (429) otomatik model değiştiren sınıf.
    """

    MODELS = ["gemini-2.5-flash-lite", "gemini-flash-lite-latest", "gemini-2.5-flash"]
    API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _ensure_complete_sentences(self, text: str) -> str:
        """
        Metin eğer nokta ile bitmiyorsa son yarım kalan parçayı temizler 
        veya nokta ekleyerek cümlenin tam bitmesini sağlar.
        """
        if not text:
            return ""

        text = text.strip()
        if text and text[-1] not in ['.', '!', '?', ':', ')', '>']:
            last_dot = max(text.rfind('.'), text.rfind('!'), text.rfind('?'))
            if last_dot > len(text) * 0.7:
                text = text[:last_dot + 1]
            else:
                text += "."

        return text

    def _clean_for_telegram(self, text: str) -> str:
        """
        Gemini AI çıktısındaki Markdown biçimlendirmelerini (bold, italic, code) 
        Telegram HTML biçimine dönüştürür ve metni temizler.
        """
        if not text:
            return ""
        import re
        # **kalın** -> <b>kalın</b>
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        # *italik* -> <i>italik</i>
        text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', text)
        # `kod` -> <code>kod</code>
        text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
        return text.strip()

    def _call_gemini_api(self, prompt: str, max_tokens: int = 1500) -> str:
        """
        Gemini API'ye istek atar. Kota aşımı (429) durumunda yedek Modellere otomatik geçiş yapar.
        """
        if not self.api_key:
            return ""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": max_tokens
            }
        }

        for model in self.MODELS:
            url = self.API_URL_TEMPLATE.format(model=model, key=self.api_key)
            try:
                resp = requests.post(url, json=payload, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        if parts:
                            raw_text = parts[0].get("text", "").strip()
                            clean_text = self._ensure_complete_sentences(raw_text)
                            return self._clean_for_telegram(clean_text)
                elif resp.status_code == 429:
                    logger.warning(f"Model '{model}' kota aşımına uğradı (429). Sonraki model deneniyor...")
                    continue
                else:
                    logger.error(f"Gemini API Model '{model}' Hata {resp.status_code}: {resp.text}")
            except Exception as err:
                logger.error(f"Gemini isteğinde hata ({model}): {err}")

        return ""

    def analyze_job(self, title: str, location: str, education: str, raw_description: str, source: str = "İŞKUR") -> str:
        """
        İlan metnini Gemini AI modeline göndererek derinlemesine analiz yaptırır.
        """
        prompt = f"""
Sen uzman bir kariyer ve kamu personel alım danışmanısın.
Aşağıda verilen resmi iş/memur ilanını dikkatle incele. Kullanıcının gözünden kaçabilecek şartları, başvuru detaylarını ve ipuçlarını çıkart.

İlan Bilgileri:
- Kaynak: {source}
- Pozisyon: {title}
- Şehir/Konum: {location}
- Öğrenim Şartı: {education}
- İlan Açıklaması & Şartlar:
{raw_description}

KRİTİK FORMAT TALİMATLARI:
1. Her cümleni tam ve eksiksiz bitir. ASLA yarım bırakma.
2. Madde aralarına ve başlık aralarına MUTLAKA çift satır boşluğu (boş satır) koy.
3. Şablon (BAŞKA ÜST BAŞLIK EKLEME):

💡 <b>Satır Arası İpuçları & İnce Detaylar:</b>

• <b>Kura / Sınav / KPSS Şartı:</b> (Açıklayıcı tam cümle.)

• <b>İkamet & Yaş Detayı:</b> (Açıklayıcı tam cümle.)

• <b>Önemli Başvuru Notu:</b> (Açıklayıcı tam cümle.)

🎯 <b>Kısaca Kimler Başvurabilir?:</b>
(Özet başvuru profili tam bir cümle ile.)
"""
        return self._call_gemini_api(prompt, max_tokens=1500)

    def ask_question_about_job(self, job_data: dict, question: str) -> str:
        """
        Kullanıcının SQLite'taki bir ilan hakkında sorduğu özel soruyu Gemini AI ile yanıtlar.
        """
        prompt = f"""
Sen yardımsever ve uzman bir kariyer danışmanısın.
Kullanıcı veritabanında saklanan şu iş/memur ilanı hakkında bir soru sordu:

İlan Kaydı:
- İlan No: {job_data.get('job_no', '')}
- Pozisyon: {job_data.get('title', '')}
- Kaynak: {job_data.get('source', '')}
- Lokasyon: {job_data.get('location', '')}
- Öğrenim Şartı: {job_data.get('education', '')}
- Son Başvuru: {job_data.get('deadline', '')}
- Detaylı İlan Metni:
{job_data.get('description', '')}

Kullanıcının Sorusu: "{question}"

KRİTİK TALİMATLAR:
- Soruyu ilandaki bilgilere ve genel kamu/iş sektörü tecrübene dayanarak açıkla.
- Eğer ilanda net maaş yazmıyorsa, bu meslek grubu/kamu kadrosu için ortalama tahmini piyasa/kamu maaş skalasını ve hakları nazikçe açıkla.
- Paragrafların arasına çift satır boşluğu koy.
- Cümlelerini ASLA yarım kesme, noktalama ile tam bitir.
- Cevabı Telegram HTML formatında ver (<b>, <i>).
"""
        res = self._call_gemini_api(prompt, max_tokens=1500)
        return res if res else "İlan detayına göre soru yanıtlanamadı."
