"""Ручная чистка собранного списка → seeds/sources.txt репозитория."""
import sys

EXCLUDE = set("""
addlist github_repos tproger_official haskellru rubyjob sapjobrus pgsql proasm qaindia forallqa jvmchat jvmjobs
laraveljob ru_laravel ru_modx ru_modx_work yiijobs mobile_dev_jobs mobile_job_ua mobile_jobs mobiledevjob mobilenewsru
work4writers work_editor textorium textodromo contentprofi targetologi_vakansii motionhunter eth_jobs
microsoftstackjobs rabotaembedded protelecom zabbixpro domainguru uabrand resume_review myresume_ru noexperience
jobforjunior junior_vacancies juniors_rabota_jobs jobs_juniors_remote itstartjob yuniorapp novobranez uiux_jobs
cgfreelance rueventjob edujobs djinni_relocate relocation_vacancies jobs_abroad evacuatejobs justbus self_ma
netology_project workinstajob forallmedia glvrd_job stage_1st theyseeku tj_collega vdhl_good jobskolkovo
alttg beardycast elementary_os eth_ru ffmpeg_ru fire_monkey fmx_ru funscience gambala_chat hashtag_whity illuminatinc
macdev_ru macosx86 midevices myobrechenychannel netbeans_ru nocproject octobercms_rus opentgresearcher ozon_int
pro_ansible pro_osdev proglibrary pwrtelegramgroupru reactivex reactnative_ru ru_arduino ru_electronics
ru_nexus_sonatype ru_voip russianfedora themarfa ty_kak_media uavpro victoriametrics_ru1 zigbeer compilerdev eoscode
laravel_pro laravel_web laravelrus livewire_ru wp4dev habr_com microsoftschool netology_ru junior_happens
ru_python_beginners pro_ionic ember_js meteorjs_ru featherjs mam_mol webgl_ru webassembly_ru
""".split())

src, dst = sys.argv[1], sys.argv[2]
header, kept, dropped = [], [], 0
for line in open(src, encoding="utf-8"):
    line = line.rstrip("\n")
    if not line.startswith(("!@", "@")):
        header.append(line)
        continue
    name = line.lstrip("!@")
    if name.lower() in EXCLUDE:
        dropped += 1
        continue
    kept.append(line)
high = [x for x in kept if x.startswith("!")]
normal = [x for x in kept if not x.startswith("!")]
with open(dst, "w", encoding="utf-8") as f:
    f.write("\n".join(header).rstrip() + "\n\n# --- вакансии, фриланс, заказы (priority 10) ---\n")
    f.write("\n".join(high) + "\n\n# --- тех-чаты по стеку: Python, веб, фронтенд, боты (priority 5) ---\n")
    f.write("\n".join(normal) + "\n")
print(f"kept high={len(high)} normal={len(normal)} dropped={dropped}")
