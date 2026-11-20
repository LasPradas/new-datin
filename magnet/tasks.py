# magnet/tasks.py
from celery import shared_task
from django.core.management import call_command
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import os


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 10})
def fill_external_form(self, selenium_data):
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")

    service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(
        service=service,
        options=chrome_options
    )

    driver.set_page_load_timeout(30)

    # pastikan folder screenshot ada
    os.makedirs("app", exist_ok=True)

    try:
        print(f"AUTOMATION DATA RECEIVED: {selenium_data}")

        url = "http://202.90.198.224:8181/absolute/DATA_INPUT.php"
        driver.get(url)

        wait = WebDriverWait(driver, 20)

        # ======================
        # DATA PENGAMAT
        # ======================
        wait.until(EC.presence_of_element_located((By.NAME, "kode_sts"))).send_keys("JYP")
        driver.find_element(By.ID, "pengamat").send_keys(selenium_data["pengamat"])
        driver.find_element(By.ID, "datepicker").send_keys(selenium_data["datepicker"])

        # ======================
        # AZIMUTH TT
        # ======================
        azimuth = selenium_data["azimuth_tt"]
        driver.find_element(By.ID, "ATT_D").send_keys(azimuth["deg"])
        driver.find_element(By.ID, "ATT_M").send_keys(azimuth["min"])
        driver.find_element(By.ID, "ATT_S").send_keys(azimuth["sec"])

        # ======================
        # BACAAAN TITIK TETAP
        # ======================
        for key in ["CR1", "CL1", "CR2", "CL2"]:
            data = selenium_data[key]
            driver.find_element(By.ID, f"{key}_D").send_keys(data["deg"])
            driver.find_element(By.ID, f"{key}_M").send_keys(data["min"])
            driver.find_element(By.ID, f"{key}_S").send_keys(data["sec"])

        # ======================
        # DEKLINASI
        # ======================
        dek_times = selenium_data["deklinasi_times"]
        dek_dms = selenium_data["deklinasi_dms"]

        for reading in ["WU", "ED", "WD", "EU"]:
            driver.find_element(By.ID, f"{reading}_T").send_keys(dek_times[reading])
            driver.find_element(By.ID, f"{reading}_D").send_keys(dek_dms[reading]["deg"])
            driver.find_element(By.ID, f"{reading}_M").send_keys(dek_dms[reading]["min"])
            driver.find_element(By.ID, f"{reading}_S").send_keys(dek_dms[reading]["sec"])

        # ======================
        # INKLINASI
        # ======================
        ink_times = selenium_data["inklinasi_times"]
        ink_dms = selenium_data["inklinasi_dms"]

        for reading in ["NU", "SD", "ND", "SU"]:
            driver.find_element(By.ID, f"{reading}_T").send_keys(ink_times[reading])
            driver.find_element(By.ID, f"{reading}_D").send_keys(ink_dms[reading]["deg"])
            driver.find_element(By.ID, f"{reading}_M").send_keys(ink_dms[reading]["min"])
            driver.find_element(By.ID, f"{reading}_S").send_keys(ink_dms[reading]["sec"])

        # ======================
        # PROTON / FTOTAL
        # ======================
        ftotals = selenium_data["inklinasi_ftotals"]
        driver.find_element(By.ID, "PPM_1").send_keys(ftotals["NU"])
        driver.find_element(By.ID, "PPM_2").send_keys(ftotals["SD"])
        driver.find_element(By.ID, "PPM_3").send_keys(ftotals["ND"])
        driver.find_element(By.ID, "PPM_4").send_keys(ftotals["SU"])

        # ======================
        # SUBMIT
        # ======================
        driver.save_screenshot("app/before_submit.png")

        submit_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
        )

        try:
            submit_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", submit_btn)

        time.sleep(3)

        driver.save_screenshot("app/after_submit.png")

        return "Successfully filled and submitted the form."

    except Exception as e:
        driver.save_screenshot("app/error.png")
        raise e

    finally:
        driver.quit()


@shared_task(autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 300})
def fetch_fmi_indices_task(date=None, jenis='all', force=False, telegram=True):
    """Celery wrapper for the fetch_fmi_indices management command.

    Dijadwalkan setiap 16:00 WIT (07:00 UTC) — lihat CELERY_BEAT_SCHEDULE.
    `date` (YYYY-MM-DD) untuk mengisi hari yang terlewat, `jenis` = K / A / all.
    `telegram=False` dipakai tombol "Ambil Sekarang": hanya jadwal 16:00 yang mengirim ke grup.
    """
    kwargs = {'jenis': jenis, 'force': force, 'no_telegram': not telegram}
    if date:
        kwargs['date'] = date

    print(f"Starting fetch_fmi_indices task... {kwargs}")
    call_command('fetch_fmi_indices', **kwargs)
    print("Finished fetch_fmi_indices task.")


@shared_task
def compute_kindex_jyp_task(start=None, end=None):
    """Hitung indeks K JYP (metode FMI) dari data mentah LEMI untuk rentang tanggal UTC.

    Tanpa argumen: kemarin lusa s.d. hari ini (hari ini & kemarin masih sementara).
    """
    import datetime as _dt

    from .kindex_fmi import store_day

    today = _dt.datetime.now(_dt.timezone.utc).date()
    start = _dt.date.fromisoformat(start) if start else today - _dt.timedelta(days=2)
    end = min(_dt.date.fromisoformat(end) if end else today, today)
    stored = []
    day = start
    while day <= end:
        _, obj = store_day(day)
        if obj is not None:
            stored.append(f'{day}: {obj.k_values}')
        day += _dt.timedelta(days=1)
    return stored


KINDEX_SENT_KEY = 'kindex-jyp-telegram-sent'


@shared_task
def send_kindex_jyp_telegram_task(force=False):
    """Kirim grafik indeks K & A JYP 7 hari (hitung lokal) ke grup Telegram, sekali per hari baru.

    Dijalankan tiap jam. Grafik berakhir di hari terakhir yang nilai K-nya sudah tetap, yaitu
    setelah server punya 4 jam pertama hari berikutnya (biasanya saat berkas hari itu tiba,
    sekitar 00:10 UTC lusa). Hari yang sudah dikirim tidak dikirim lagi (`force` untuk ulang).
    Citra yang sama disimpan ke cache halaman publik /magnetbumi/indeks-k-a/.
    """
    import datetime as _dt

    from django.core.cache import cache
    from theme.telegram import send_telegram_photo
    from .kindex_plot import PNG_CACHE_SECONDS, latest_day, png_cache_key, render_a_png, render_k_png
    from .models import KIndexDaily

    end = latest_day()
    if end is None:
        return 'tidak ada data indeks K'
    sent = cache.get(KINDEX_SENT_KEY)
    if not force and sent and _dt.date.fromisoformat(sent) >= end:
        return f'{end} sudah dikirim'
    if not force and end < _dt.datetime.now(_dt.timezone.utc).date() - _dt.timedelta(days=4):
        return f'{end} terlalu lama, tidak dikirim'   # mis. sesudah LEMI lama mati
    obj = KIndexDaily.objects.get(tanggal=end)
    png_k, png_a = render_k_png(end), render_a_png(end)
    cache.set(png_cache_key('k', end), png_k, PNG_CACHE_SECONDS)
    cache.set(png_cache_key('a', end), png_a, PNG_CACHE_SECONDS)
    caption = (f'🧭 <b>Indeks Magnetbumi K &amp; A — Jayapura (JYP)</b>\n'
               f'📅 7 hari s.d. {end:%d-%m-%Y} UTC\n'
               f'Hari terakhir: A={obj.a_index:.0f} ({obj.criteria_label})'
               + (f' — {obj.keterangan}' if obj.keterangan else '')
               + '\n<i>Hitung lokal metode FMI dari data LEMI-018 JYP</i>')
    ok_k = send_telegram_photo(png_k, f'Indeks-K-JYP-{end:%Y%m%d}.png', caption=caption)
    ok_a = send_telegram_photo(png_a, f'Indeks-A-JYP-{end:%Y%m%d}.png',
                               caption=f'Indeks A harian JYP s.d. {end:%d-%m-%Y}')
    if ok_k:
        cache.set(KINDEX_SENT_KEY, end.isoformat(), None)
    return f'{end}: K terkirim={ok_k}, A terkirim={ok_a}'


LEMI_DOWN_KEY = 'lemi-data-down-since'
# Watchdog di PC .105 melapor 'ok' tiap 4 menit selama data segar; 40 menit tanpa 'ok' berarti
# program macet tanpa pulih, PC mati, atau jaringan putus.
LEMI_STALE_MINUTES = 40
LEMI_SYNC_DOWN_KEY = 'lemi-raw-sync-down-since'
# Berkas mentah dikirim setelah ditutup (00:00 UTC atau saat LEMI dimulai ulang), jadi sampel
# terakhir di server bisa berumur hampir 24 jam. Lewat 26 jam berarti pengiriman macet.
LEMI_SYNC_STALE_HOURS = 26


def latest_lemi_sample(raw_dir):
    """Waktu UTC sampel terakhir di berkas mentah terbaru, atau None."""
    import datetime as _dt
    from pathlib import Path

    files = sorted(p for p in Path(raw_dir).glob('*.txt') if p.name[:4].isdigit()) if Path(raw_dir).is_dir() else []
    for path in reversed(files[-5:]):
        with open(path, 'rb') as fh:
            fh.seek(0, 2)
            fh.seek(max(fh.tell() - 400, 0))
            lines = fh.read().decode('ascii', 'ignore').splitlines()
        for line in reversed(lines):
            parts = line.split()
            try:
                return _dt.datetime(*(int(v) for v in parts[:6]), tzinfo=_dt.timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


@shared_task
def check_lemi_data_task():
    """Peringatan Telegram untuk LEMI-018, sekali saat bermasalah dan sekali saat pulih.

    1. LEMI hidup? Dinilai dari laporan 'ok' watchdog PC .105 (lemi_watchdog.ps1), yang hanya
       melapor 'ok' selama datanya segar. Bukan dari data mentah: berkas yang sedang ditulis
       sengaja tidak dikirim (membukanya membuat lemi018.exe berhenti merekam).
    2. Pengiriman data mentah (lemi_raw_sync.ps1) jalan? Sampel terakhir di server < 26 jam.
    """
    import datetime as _dt

    from django.conf import settings
    from django.core.cache import cache
    from theme.telegram import send_telegram_message
    from .models import InstrumentStatus

    now = _dt.datetime.now(_dt.timezone.utc)
    fmt = '%d-%m-%Y %H:%M UTC'
    result = []

    def watch(key, problem, last, problem_msg, ok_msg):
        down_since = cache.get(key)
        if problem:
            if not down_since and send_telegram_message(problem_msg):
                cache.set(key, last.isoformat(), None)
            return
        if down_since and send_telegram_message(ok_msg(_dt.datetime.fromisoformat(down_since))):
            cache.delete(key)

    ok = (InstrumentStatus.objects.filter(instrument=InstrumentStatus.LEMI, status=InstrumentStatus.STATUS_OK)
          .order_by('-reported_at').values_list('reported_at', flat=True).first())
    if ok is None:
        result.append('belum ada laporan watchdog')
    else:
        late = (now - ok).total_seconds() / 60
        watch(LEMI_DOWN_KEY, late > LEMI_STALE_MINUTES, ok,
              f'⚠️ <b>LEMI-018 tidak melapor data segar</b>\n'
              f'Laporan OK terakhir dari watchdog {ok.strftime(fmt)} ({late:.0f} menit lalu).\n'
              f'Periksa program LEMI di PC 172.21.63.105 (not responding / tertutup), PC, dan jaringan.',
              lambda since: f'✅ <b>LEMI-018 melapor lagi</b>\n'
                            f'Berhenti sejak {since.strftime(fmt)}, laporan OK terakhir {ok.strftime(fmt)}.')
        result.append(f'watchdog terlambat {late:.0f} menit' if late > LEMI_STALE_MINUTES else 'watchdog ok')

    last = latest_lemi_sample(settings.LEMI_RAW_DIR)
    if last is None:
        result.append('belum ada data')
    else:
        hours = (now - last).total_seconds() / 3600
        watch(LEMI_SYNC_DOWN_KEY, hours > LEMI_SYNC_STALE_HOURS, last,
              f'⚠️ <b>Data mentah LEMI-018 tidak terkirim ke server</b>\n'
              f'Sampel terakhir di server {last.strftime(fmt)} ({hours:.0f} jam lalu).\n'
              f'Periksa task LEMIRawSync di PC 172.21.63.105 (C:\\lemi_raw_sync\\lemi_raw_sync.log).',
              lambda since: f'✅ <b>Data mentah LEMI-018 terkirim lagi</b>\n'
                            f'Berhenti sejak {since.strftime(fmt)}, sampel terakhir {last.strftime(fmt)}.')
        result.append(f'data mentah terlambat {hours:.0f} jam' if hours > LEMI_SYNC_STALE_HOURS else 'data mentah ok')
    return ', '.join(result)
