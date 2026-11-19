from django.urls import path
from . import views

app_name = 'perjadin'
urlpatterns = [
    path('', views.index_perjadin, name='index_perjadin'),
    path('tambah/', views.tambah_perjadin, name='tambah_perjadin'),
    path('detail/<int:pegawai_id>/', views.detail_pegawai, name='detail_perjadin'),
    path('edit/<int:trip_id>/', views.edit_perjadin, name='edit_perjadin'),
    path('hapus/<int:trip_id>/', views.hapus_perjadin, name='hapus_perjadin'),
]