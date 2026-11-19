import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from jadwal.models import Pegawai
from .models import JenisPerjadin, PerjalananDinas


def make_jenis(**kwargs):
    defaults = dict(nama='Harian Luar Kota', tarif_harian=500000)
    defaults.update(kwargs)
    return JenisPerjadin.objects.create(**defaults)


def make_pegawai(**kwargs):
    user = User.objects.create_user('pegawai_user', password='pass123')
    defaults = dict(
        user=user,
        nama='Jambari',
        nip='197001011990031001',
        pangkat='Penata (III/c)',
        jabatan='PMG Muda',
    )
    defaults.update(kwargs)
    return Pegawai.objects.create(**defaults)


def make_perjadin(pegawai, jenis, **kwargs):
    defaults = dict(
        pegawai=pegawai,
        jenis=jenis,
        tujuan='Jakarta',
        kegiatan='Pelatihan',
        tgl_mulai=datetime.date(2024, 3, 1),
        tgl_selesai=datetime.date(2024, 3, 5),
    )
    defaults.update(kwargs)
    return PerjalananDinas.objects.create(**defaults)


class JenisPerjadnModelTest(TestCase):
    def test_create_and_str(self):
        j = make_jenis()
        self.assertIn('Harian Luar Kota', str(j))

    def test_tarif_displayed_in_str(self):
        j = make_jenis(tarif_harian=750000)
        self.assertIn('750', str(j))


class PerjalananDinasModelTest(TestCase):
    def setUp(self):
        self.pegawai = make_pegawai()
        self.jenis = make_jenis()

    def test_create(self):
        p = make_perjadin(self.pegawai, self.jenis)
        self.assertEqual(p.tujuan, 'Jakarta')

    def test_durasi_hari_property(self):
        p = make_perjadin(
            self.pegawai, self.jenis,
            tgl_mulai=datetime.date(2024, 3, 1),
            tgl_selesai=datetime.date(2024, 3, 5),
        )
        self.assertEqual(p.durasi_hari, 5)

    def test_total_biaya_property(self):
        p = make_perjadin(
            self.pegawai, self.jenis,
            tgl_mulai=datetime.date(2024, 3, 1),
            tgl_selesai=datetime.date(2024, 3, 5),
        )
        self.assertEqual(p.total_biaya, 5 * 500000)

    def test_single_day_durasi(self):
        p = make_perjadin(
            self.pegawai, self.jenis,
            tgl_mulai=datetime.date(2024, 3, 1),
            tgl_selesai=datetime.date(2024, 3, 1),
        )
        self.assertEqual(p.durasi_hari, 1)


class PerjalananDinasViewsTest(TestCase):
    def setUp(self):
        self.client = Client()
        # authorized user
        self.jambari = User.objects.create_user('jambari', password='pass123')
        # unauthorized user
        self.other = User.objects.create_user('other', password='pass123')
        self.jenis = make_jenis()
        self.pegawai = make_pegawai()

    def test_index_perjadin_authorized_user(self):
        self.client.login(username='jambari', password='pass123')
        resp = self.client.get(reverse('perjadin:index_perjadin'))
        self.assertEqual(resp.status_code, 200)

    def test_index_perjadin_unauthorized_user_returns_403(self):
        self.client.login(username='other', password='pass123')
        resp = self.client.get(reverse('perjadin:index_perjadin'))
        self.assertEqual(resp.status_code, 403)

    def test_index_perjadin_unauthenticated_returns_403(self):
        resp = self.client.get(reverse('perjadin:index_perjadin'))
        self.assertEqual(resp.status_code, 403)

    def test_tambah_perjadin_post_authorized(self):
        self.client.login(username='jambari', password='pass123')
        resp = self.client.post(reverse('perjadin:tambah_perjadin'), {
            'pegawai': self.pegawai.id,
            'jenis': self.jenis.id,
            'tujuan': 'Jakarta',
            'kegiatan': 'Workshop',
            'tgl_mulai': '2024-03-01',
            'tgl_selesai': '2024-03-03',
        })
        self.assertIn(resp.status_code, [200, 302])

    def _post_new(self, **extra):
        data = {
            'pegawai': self.pegawai.id, 'jenis': self.jenis.id,
            'tujuan': 'Sentani', 'kegiatan': 'CM', 'tgl_mulai': '2026-11-18',
            'tgl_selesai': '2026-11-20', **extra,
        }
        return self.client.post(reverse('perjadin:tambah_perjadin'), data, follow=True)

    def test_tambah_without_current_month_redirects_to_trip_month(self):
        # Form lama tidak mengirim current_month/current_year -> dulu 500 (month=None)
        self.client.login(username='jambari', password='pass123')
        resp = self._post_new()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.redirect_chain[-1][0], '/perjadin/?month=11&year=2026')
        self.assertEqual(PerjalananDinas.objects.filter(tujuan='Sentani').count(), 1)

    def test_tambah_returns_to_month_being_viewed(self):
        self.client.login(username='jambari', password='pass123')
        resp = self._post_new(current_month='10', current_year='2026')
        self.assertEqual(resp.redirect_chain[-1][0], '/perjadin/?month=10&year=2026')

    def test_tambah_duplicate_also_redirects_ok(self):
        self.client.login(username='jambari', password='pass123')
        self._post_new()
        resp = self._post_new()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PerjalananDinas.objects.filter(tujuan='Sentani').count(), 1)

    def test_tambah_rejects_end_before_start(self):
        self.client.login(username='jambari', password='pass123')
        resp = self._post_new(tgl_mulai='2026-05-26', tgl_selesai='2026-04-26')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(PerjalananDinas.objects.filter(tujuan='Sentani').exists())

    def test_tambah_rejects_bad_date(self):
        self.client.login(username='jambari', password='pass123')
        resp = self._post_new(tgl_mulai='26-05-2026')
        self.assertEqual(resp.status_code, 400)

    def test_tambah_unauthorized_returns_403(self):
        self.client.login(username='other', password='pass123')
        resp = self._post_new()
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(PerjalananDinas.objects.filter(tujuan='Sentani').exists())

    def test_index_invalid_month_falls_back(self):
        self.client.login(username='jambari', password='pass123')
        resp = self.client.get(reverse('perjadin:index_perjadin'), {'month': 'None', 'year': 'None'})
        self.assertEqual(resp.status_code, 200)

    def test_index_form_sends_current_month(self):
        self.client.login(username='jambari', password='pass123')
        resp = self.client.get(reverse('perjadin:index_perjadin'), {'month': 10, 'year': 2026})
        self.assertContains(resp, 'name="current_month" value="10"')
        self.assertContains(resp, 'name="current_year" value="2026"')

    def test_detail_pegawai_authorized(self):
        self.client.login(username='jambari', password='pass123')
        resp = self.client.get(reverse('perjadin:detail_perjadin', args=[self.pegawai.id]))
        self.assertIn(resp.status_code, [200, 302])

    def test_detail_pegawai_404_on_invalid(self):
        self.client.login(username='jambari', password='pass123')
        resp = self.client.get(reverse('perjadin:detail_perjadin', args=[9999]))
        self.assertEqual(resp.status_code, 404)


class PerjadinEditHapusTest(TestCase):
    def setUp(self):
        User.objects.create_user('jambari', password='pass123')
        User.objects.create_user('other', password='pass123')
        self.jenis = make_jenis()
        self.jenis_kota = make_jenis(nama='Dalam Kota', tarif_harian=170000)
        self.pegawai = make_pegawai()
        self.pegawai2 = Pegawai.objects.create(
            user=User.objects.create_user('pegawai2', password='x'),
            nama='Lidya', nip='2', pangkat='-', jabatan='-')
        kw = dict(tujuan='Jayapura', kegiatan='PM Sirine',
                  tgl_mulai=datetime.date(2026, 5, 26), tgl_selesai=datetime.date(2026, 5, 26))
        self.trip = make_perjadin(self.pegawai, self.jenis_kota, **kw)
        self.trip2 = make_perjadin(self.pegawai2, self.jenis_kota, **kw)   # peserta lain, kegiatan sama

    def _login(self, username='jambari'):
        self.client.login(username=username, password='pass123')

    def _edit_data(self, **extra):
        data = {'pegawai': self.pegawai.id, 'jenis': self.jenis.id, 'tujuan': 'Keerom',
                'kegiatan': 'PM ARPI', 'tgl_mulai': '2026-05-26', 'tgl_selesai': '2026-05-28',
                'current_month': '11', 'current_year': '2026'}
        data.update(extra)
        return data

    def test_detail_modal_has_edit_and_hapus(self):
        self._login()
        resp = self.client.get(reverse('perjadin:detail_perjadin', args=[self.pegawai.id]),
                               {'month': 11, 'year': 2026})
        self.assertContains(resp, reverse('perjadin:edit_perjadin', args=[self.trip.id]))
        self.assertContains(resp, reverse('perjadin:hapus_perjadin', args=[self.trip.id]))
        self.assertContains(resp, 'name="current_month" value="11"')

    def test_detail_requires_jambari(self):
        self._login('other')
        resp = self.client.get(reverse('perjadin:detail_perjadin', args=[self.pegawai.id]))
        self.assertEqual(resp.status_code, 403)

    def test_edit_get_prefills(self):
        self._login()
        resp = self.client.get(reverse('perjadin:edit_perjadin', args=[self.trip.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'value="2026-05-26"')
        self.assertContains(resp, 'value="PM Sirine"')

    def test_edit_saves_only_this_pegawai(self):
        self._login()
        resp = self.client.post(reverse('perjadin:edit_perjadin', args=[self.trip.id]), self._edit_data())
        self.assertRedirects(resp, '/perjadin/?month=11&year=2026', fetch_redirect_response=False)
        self.trip.refresh_from_db()
        self.trip2.refresh_from_db()
        self.assertEqual((self.trip.tujuan, self.trip.durasi_hari, self.trip.jenis_id), ('Keerom', 3, self.jenis.id))
        self.assertEqual(self.trip2.tujuan, 'Jayapura')

    def test_edit_rejects_reversed_dates(self):
        self._login()
        resp = self.client.post(reverse('perjadin:edit_perjadin', args=[self.trip.id]),
                                self._edit_data(tgl_selesai='2026-04-26'))
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, 'Tgl Selesai tidak boleh sebelum Tgl Mulai', status_code=400)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.tujuan, 'Jayapura')

    def test_edit_missing_month_redirects_to_trip_month(self):
        self._login()
        resp = self.client.post(reverse('perjadin:edit_perjadin', args=[self.trip.id]),
                                self._edit_data(current_month='', current_year=''))
        self.assertRedirects(resp, '/perjadin/?month=5&year=2026', fetch_redirect_response=False)

    def test_edit_requires_jambari(self):
        self._login('other')
        resp = self.client.post(reverse('perjadin:edit_perjadin', args=[self.trip.id]), self._edit_data())
        self.assertEqual(resp.status_code, 403)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.tujuan, 'Jayapura')

    def test_hapus_deletes_only_this_pegawai(self):
        self._login()
        resp = self.client.post(reverse('perjadin:hapus_perjadin', args=[self.trip.id]),
                                {'current_month': '11', 'current_year': '2026'})
        self.assertRedirects(resp, '/perjadin/?month=11&year=2026', fetch_redirect_response=False)
        self.assertFalse(PerjalananDinas.objects.filter(id=self.trip.id).exists())
        self.assertTrue(PerjalananDinas.objects.filter(id=self.trip2.id).exists())

    def test_hapus_get_not_allowed(self):
        self._login()
        resp = self.client.get(reverse('perjadin:hapus_perjadin', args=[self.trip.id]))
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(PerjalananDinas.objects.filter(id=self.trip.id).exists())

    def test_hapus_requires_jambari(self):
        self._login('other')
        resp = self.client.post(reverse('perjadin:hapus_perjadin', args=[self.trip.id]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(PerjalananDinas.objects.filter(id=self.trip.id).exists())
