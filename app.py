"""
Türkiye'de internet altyapısı (fiber/VDSL/ADSL) sorgulamak için örnek bir Streamlit uygulaması.

⚠️ Notlar
- Resmî ISS sayfalarının çoğu açık API sunmaz; e-Devlet (BTK EHABS) oturum ister. Bu uygulama, modüler bir
  "sağlayıcı (provider)" mimarisiyle çalışır: varsa API anahtarınızı girip kullanın; yoksa yönlendirme linkleri
  ve manuel TT Adres Kodu ile sorgu akışı sağlar.
- Demo amaçlı bir "mock" sağlayıcı dâhil edilmiştir. Gerçek sonuçlar için aşağıdaki sağlayıcı sınıflarını
  kendi erişim bilgilerinizle doldurun.

Çalıştırma
1) Python 3.10+ kurulu olmalı.
2) Gerekli paketleri kurun:  pip install streamlit requests pydantic
3) Uygulamayı başlatın:      streamlit run app.py

Dosyayı app.py olarak kaydedip çalıştırabilirsiniz.
"""

from __future__ import annotations
import os
import time
from typing import List, Optional, Dict, Any

import requests
import streamlit as st
from pydantic import BaseModel, Field, validator

# ---------------------------
# Veri Modelleri
# ---------------------------
class Address(BaseModel):
    il: str = Field(..., description="İl")
    ilce: str = Field(..., description="İlçe")
    mahalle: Optional[str] = Field("", description="Mahalle")
    cadde_sokak: Optional[str] = Field("", description="Cadde/Sokak")
    bina_no: Optional[str] = Field("", description="Bina No")
    daire: Optional[str] = Field("", description="Daire")
    tt_adres_kodu: Optional[str] = Field("", description="Türk Telekom Adres Kodu (varsa)")

    @validator("il", "ilce")
    def non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Bu alan zorunludur")
        return v

class InfraResult(BaseModel):
    provider: str
    technology: str  # Fiber / VDSL / ADSL / Yok / Belirsiz
    max_down_mbps: Optional[float] = None
    max_up_mbps: Optional[float] = None
    port_available: Optional[bool] = None
    raw: Dict[str, Any] = Field(default_factory=dict)

# ---------------------------
# Sağlayıcı Arabirimi
# ---------------------------
class Provider:
    name: str = "Base"
    def query(self, address: Address) -> List[InfraResult]:
        raise NotImplementedError

# 1) Demo / Mock Sağlayıcı: adres girdilerine basit kuralla sonuç üretir
class MockProvider(Provider):
    name = "Demo (Mock)"
    def query(self, address: Address) -> List[InfraResult]:
        key = f"{address.il.lower()}-{address.ilce.lower()}"
        # Tamamen örnek mantık: Karadeniz illerinde fiber olasılığını yüksek sayalım :)
        karadeniz = {"rize","artvin","trabzon","giresun","ordu","samsun","bartin","kastamonu","sinop","zonguldak"}
        tech = "Fiber" if address.il.lower() in karadeniz else "VDSL"
        down = 1000 if tech == "Fiber" else 100
        up = 100 if tech == "Fiber" else 8
        return [InfraResult(provider=self.name, technology=tech, max_down_mbps=down, max_up_mbps=up, port_available=True, raw={"rule":"demo"})]

# 2) Wiradius TT VAE örneği (isteğe bağlı): API anahtarınız varsa doldurun
class WiradiusTTProvider(Provider):
    name = "Wiradius – TT VAE (Opsiyonel)"
    def __init__(self, api_code: str = "", uniq_code: str = ""):
        self.api_code = api_code
        self.uniq_code = uniq_code

    def query(self, address: Address) -> List[InfraResult]:
        if not (self.api_code and self.uniq_code and address.tt_adres_kodu):
            # Gerekli bilgiler yoksa boş liste döndür
            return []
        url = f"https://api.wiradius.com/internet_infrastructure/tt_vae_query/{self.api_code}"
        payload = {"tt_code": address.tt_adres_kodu, "uniq_code": self.uniq_code}
        try:
            resp = requests.post(url, json=payload, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            # Bu kısım, gerçek yanıta göre uyarlanmalı (Postman sayfasındaki alan adlarını kontrol edin)
            tech = data.get("technology") or data.get("tech") or "Belirsiz"
            max_down = data.get("max_down") or data.get("download")
            max_up = data.get("max_up") or data.get("upload")
            port_avail = data.get("port_available")
            return [InfraResult(provider=self.name, technology=str(tech), max_down_mbps=max_down, max_up_mbps=max_up, port_available=port_avail, raw=data)]
        except Exception as e:
            return [InfraResult(provider=self.name, technology="Hata", raw={"error": str(e)})]

# 3) Yönlendirme sağlayıcısı: resmî sorgu sayfalarına link verir (TT, Superonline, Millenicom, Netspeed)
class LinkOutProvider(Provider):
    name = "Resmî Sayfalar – Yönlendirme"
    LINKS = {
        "Türk Telekom Altyapı Sorgu": "https://www.turktelekom.com.tr/altyapi-sorgulama",
        "TT Kapsama Haritası": "https://kapsamaharitasi.turktelekom.com.tr/",
        "Turkcell Superonline": "https://www.superonline.net/altyapi-sorgulama",
        "Turkcell (Superbox/Altyapı)": "https://www.turkcell.com.tr/tr/altyapi-sorgulama",
        "Millenicom": "https://www.milleni.com.tr/internet-altyapi-sorgulama",
        "Netspeed": "https://www.netspeed.com.tr/altyapi-sorgula",
        "BTK – EHABS (e-Devlet)": "https://www.turkiye.gov.tr/btk-elektronik-haberlesme-altyapi-bilgi-sistemi-ehabs-hizmetleri-4302",
    }
    def query(self, address: Address) -> List[InfraResult]:
        return [InfraResult(provider=self.name, technology="Yönlendirme", raw=self.LINKS)]

# ---------------------------
# Yardımcılar
# ---------------------------
PROVIDERS: List[Provider] = []

# Ortam değişkeniyle opsiyonel Wiradius anahtarlarını al
WIR_API = os.getenv("WIRADIUS_API_CODE", "")
WIR_UNIQ = os.getenv("WIRADIUS_UNIQ_CODE", "")

PROVIDERS.append(MockProvider())
PROVIDERS.append(WiradiusTTProvider(api_code=WIR_API, uniq_code=WIR_UNIQ))
PROVIDERS.append(LinkOutProvider())

# ---------------------------
# UI – Streamlit
# ---------------------------
st.set_page_config(page_title="Türkiye Altyapı Sorgu", page_icon="🛰️", layout="centered")
st.title("🛰️ Türkiye İnternet Altyapı Sorgu")
st.caption("Fiber/VDSL uygunluğu için adres bazlı demo uygulaması · Sağlayıcı eklentili mimari")

with st.form("address_form"):
    col1, col2 = st.columns(2)
    with col1:
        il = st.text_input("İl", value="Rize")
        mahalle = st.text_input("Mahalle")
        bina_no = st.text_input("Bina No")
    with col2:
        ilce = st.text_input("İlçe", value="Merkez")
        cadde = st.text_input("Cadde/Sokak")
        daire = st.text_input("Daire")
    tt_kod = st.text_input("Türk Telekom Adres Kodu (opsiyonel)")

    with st.expander("🔑 Opsiyonel – Wiradius TT VAE API Ayarları"):
        st.write("Uygulamayı çalıştırmadan önce ortam değişkeni geçebilir ya da buraya girip geçici kullanabilirsiniz.")
        wir_api_input = st.text_input("WIRADIUS_API_CODE", type="password")
        wir_uniq_input = st.text_input("WIRADIUS_UNIQ_CODE", type="password")

    submitted = st.form_submit_button("Sorgula")

if submitted:
    try:
        address = Address(il=il, ilce=ilce, mahalle=mahalle, cadde_sokak=cadde, bina_no=bina_no, daire=daire, tt_adres_kodu=tt_kod)
        # Eğer formda girilmişse geçici olarak sağlayıcıyı yeniden oluştur
        active_providers: List[Provider] = [MockProvider()]
        if wir_api_input and wir_uniq_input:
            active_providers.append(WiradiusTTProvider(api_code=wir_api_input, uniq_code=wir_uniq_input))
        else:
            # Ortamdan gelen varsa onu kullan
            if WIR_API and WIR_UNIQ:
                active_providers.append(WiradiusTTProvider(api_code=WIR_API, uniq_code=WIR_UNIQ))
        active_providers.append(LinkOutProvider())

        st.subheader("Sonuçlar")
        results: List[InfraResult] = []
        for p in active_providers:
            with st.spinner(f"{p.name} sorgulanıyor..."):
                time.sleep(0.2)  # kozmetik gecikme
                res = p.query(address)
                results.extend(res)

        for r in results:
            with st.container(border=True):
                st.markdown(f"**Sağlayıcı:** {r.provider}")
                st.markdown(f"**Teknoloji:** {r.technology}")
                cols = st.columns(3)
                with cols[0]:
                    st.metric("Maks. İndirme (Mbps)", r.max_down_mbps if r.max_down_mbps is not None else "-")
                with cols[1]:
                    st.metric("Maks. Yükleme (Mbps)", r.max_up_mbps if r.max_up_mbps is not None else "-")
                with cols[2]:
                    st.metric("Port Uygunluğu", "Var" if r.port_available else ("-" if r.port_available is None else "Yok"))

                if r.provider.startswith("Resmî") and r.raw:
                    st.markdown("**Hızlı Linkler**")
                    for label, url in r.raw.items():
                        st.link_button(label, url)

                with st.expander("Ham Yanıt / Detaylar"):
                    st.json(r.raw)

    except Exception as e:
        st.error(f"Form doğrulama hatası: {e}")

st.divider()
st.markdown(
    """
**Nasıl genişletilir?**
- Yeni bir ISS için sınıf ekleyin (\`Provider\`'ı kalıtın) ve \`query\` metodunda gerçek API'nizi çağırın.
- e-Devlet/EHABS gibi oturum isteyen sayfalara otomasyon yapılması genelde tavsiye edilmez (KVKK/ToS). Bunun yerine
  kullanıcıyı resmî sayfaya yönlendirip çıkan sonuçların TT Adres Kodu veya ekran görüntüsü ile manuel girilmesini sağlayabilirsiniz.
- Kurumsal entegrasyonlarda adres standardizasyonu ve \"BBK\" (Bina Bilgisi Kodu) gibi alanlar önemlidir; veri kalitesi için
  Zorunlu alanları arttırmayı düşünebilirsiniz.
"""
)
