"""Generate nine original SVG landscape placeholders; no external assets."""

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "content/images/slow-days-v1"


def svg(body: str, sky: str, seed: int) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1500" viewBox="0 0 1200 1500" role="img">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop stop-color="{sky}"/><stop offset="1" stop-color="#f4e3c7"/></linearGradient>
    <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency=".66" numOctaves="3" seed="{seed}" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter>
  </defs>
  <rect width="1200" height="1500" fill="url(#sky)"/>
  {body}
  <rect width="1200" height="1500" filter="url(#grain)" opacity=".075"/>
</svg>'''


ART = [
    ("风穿过石门", "#ead7b8", '''
      <circle cx="840" cy="340" r="130" fill="#f7edcd"/>
      <path d="M0 910 Q240 770 500 840 T1200 785 V1500 H0Z" fill="#d4b28a"/>
      <path d="M0 1060 Q310 920 670 1005 T1200 930 V1500 H0Z" fill="#c58c68"/>
      <path d="M140 1500 V620 C140 215 800 160 870 610 L1010 1500H724L656 680C635 501 396 510 378 697L370 1500Z" fill="#b66346"/>
      <path d="M140 1500V620C140 215 800 160 870 610L1010 1500H893L779 611C722 297 278 322 260 667L255 1500Z" fill="#c77954"/>
      <path d="M378 697C396 510 635 501 656 680L724 1500H370Z" fill="#edc899"/>
      <path d="M373 1090 Q500 1040 682 1110 L724 1500H370Z" fill="#d5a678"/>
      <path d="M0 1390Q340 1280 620 1360T1200 1325V1500H0Z" fill="#a7563e"/>
      <path d="M80 1420Q370 1320 620 1400" fill="none" stroke="#d89e73" stroke-width="4" opacity=".6"/>
    '''),
    ("光落在海岸", "#efe1c5", '''
      <circle cx="880" cy="315" r="105" fill="#f7f0d8"/>
      <path d="M0 630H1200V1500H0Z" fill="#769d9a"/>
      <path d="M0 780Q370 730 760 810T1200 790V1500H0Z" fill="#548380"/>
      <path d="M0 1500V960C180 858 170 730 310 700C470 666 510 600 530 552L840 570C822 738 714 850 634 971C556 1080 626 1241 430 1500Z" fill="#f0d8ae"/>
      <path d="M0 1500V975C160 880 230 791 330 772C460 748 565 648 580 568L714 570C690 722 590 832 530 948C443 1120 495 1320 305 1500Z" fill="#b18d62"/>
      <path d="M0 1500V1075C120 1000 221 929 275 830C307 775 378 746 410 695L530 650C490 817 348 910 366 1075C386 1250 240 1400 185 1500Z" fill="#8a8e65"/>
      <path d="M850 690h220M760 890h250M805 1090h290M670 1290h210" stroke="#d5e0c9" stroke-width="3" opacity=".6"/>
      <path d="M840 570C822 738 714 850 634 971C556 1080 626 1241 430 1500" fill="none" stroke="#fcf0d9" stroke-width="12"/>
    '''),
    ("柔软的地平线", "#efcfaa", '''
      <circle cx="605" cy="420" r="145" fill="#d78658"/>
      <path d="M0 860Q320 690 630 855T1200 810V1500H0Z" fill="#d5a16f"/>
      <path d="M0 1090C300 1030 470 720 760 740C895 752 1022 830 1200 872V1500H0Z" fill="#b8774f"/>
      <path d="M0 1090C300 1030 470 720 760 740C620 828 535 1114 440 1500H0Z" fill="#deb381"/>
      <path d="M0 1420C350 1222 900 1075 1200 1180V1500H0Z" fill="#8f563d"/>
      <path d="M0 1420C350 1222 900 1075 1200 1180C956 1202 806 1334 721 1500H0Z" fill="#bc865c"/>
      <path d="M560 892Q600 835 665 799M188 1320Q300 1262 400 1236" fill="none" stroke="#e8bc89" stroke-width="3" opacity=".7"/>
    '''),
    ("山谷藏着秘密", "#d7d6c0", '''
      <circle cx="820" cy="350" r="90" fill="#f0e8ca"/>
      <path d="M0 765 225 470 400 685 670 360 945 735 1200 540V1500H0Z" fill="#a5b29b"/>
      <path d="M0 1040 340 700 620 960 880 640 1200 850V1500H0Z" fill="#718c79"/>
      <path d="M0 1180Q300 1050 610 1100T1200 990V1500H0Z" fill="#426c5f"/>
      <path d="M690 980C660 1110 820 1190 680 1320C625 1370 590 1430 610 1500H900C760 1400 900 1330 800 1200C745 1130 715 1050 720 980Z" fill="#c2c3a1"/>
      <g fill="#294e47"><path d="M160 680 70 930H125L45 1120H275L195 930H250Z"/><path d="M325 910 260 1090H300L240 1220H410L350 1090H392Z"/><path d="M1040 1000 950 1220H1000L920 1410H1160L1080 1220H1130Z"/></g>
      <path d="M0 1430Q260 1360 480 1450T1200 1390V1500H0Z" fill="#23483f"/>
    '''),
    ("蓝色没有尽头", "#c9dadd", '''
      <circle cx="915" cy="300" r="88" fill="#f3e5c6"/>
      <path d="M0 590H1200V1500H0Z" fill="#7ca6ac"/>
      <path d="M0 790Q450 760 1200 850V1500H0Z" fill="#457f8c"/>
      <path d="M0 0H215C175 295 250 490 450 653C650 816 672 1010 520 1100C315 1220 430 1390 710 1500H0Z" fill="#c7b798"/>
      <path d="M0 0H135C90 295 170 500 360 690C490 820 500 1000 350 1100C200 1200 245 1400 420 1500H0Z" fill="#8e9b81"/>
      <path d="M215 0C175 295 250 490 450 653C650 816 672 1010 520 1100C315 1220 430 1390 710 1500" fill="none" stroke="#f1e7ce" stroke-width="18"/>
      <path d="M750 840h260M700 1000h390M790 1180h230M900 1370h210" stroke="#a8c3c0" stroke-width="3" opacity=".65"/>
      <path d="M830 675l60-20 45 20Z" fill="#efe8d3"/>
      <path d="M889 655v-65l-40 65Z" fill="#f3eada"/>
    '''),
    ("橄榄色的午后", "#eee2be", '''
      <circle cx="360" cy="350" r="100" fill="#dec794"/>
      <path d="M0 780Q250 620 560 760T1200 680V1500H0Z" fill="#bac099"/>
      <path d="M0 1000Q380 700 760 960T1200 810V1500H0Z" fill="#929f70"/>
      <path d="M0 1180Q390 960 700 1120T1200 1020V1500H0Z" fill="#6c815a"/>
      <path d="M850 800C720 1000 770 1110 600 1220C480 1300 380 1410 375 1500H540C550 1360 650 1310 700 1260C850 1100 800 1000 890 830Z" fill="#dec9a1"/>
      <g fill="#4d674b"><ellipse cx="170" cy="1055" rx="100" ry="75"/><ellipse cx="260" cy="1020" rx="90" ry="90"/><ellipse cx="350" cy="1060" rx="95" ry="70"/></g>
      <path d="M270 1080 256 1310M270 1170 205 1100M266 1190 325 1100" fill="none" stroke="#6c6550" stroke-width="20"/>
      <path d="M0 1390Q280 1300 570 1430T1200 1320V1500H0Z" fill="#4f6b4a"/>
      <g fill="#7b8c61"><ellipse cx="960" cy="1220" rx="70" ry="50"/><ellipse cx="1030" cy="1190" rx="65" ry="65"/><ellipse cx="1090" cy="1225" rx="65" ry="45"/></g>
      <path d="M1035 1230v120" stroke="#655d45" stroke-width="15"/>
    '''),
    ("沿着峡谷慢行", "#e9c4a6", '''
      <circle cx="630" cy="365" r="105" fill="#f5ddb4"/>
      <path d="M0 670 220 490 370 660 630 590 950 715 1200 510V1500H0Z" fill="#c88c6b"/>
      <path d="M0 0H350L320 320 480 520 410 760 560 930 440 1230 610 1500H0Z" fill="#b25c43"/>
      <path d="M0 0H135L200 300 140 580 270 850 200 1150 360 1500H0Z" fill="#8e463a"/>
      <path d="M1200 310 950 390 1020 650 870 850 940 1015 760 1260 810 1500H1200Z" fill="#a94d3b"/>
      <path d="M1200 500 1080 590 1130 790 1030 1000 1080 1210 960 1500H1200Z" fill="#743f37"/>
      <path d="M570 900C710 1020 570 1200 610 1300C640 1390 750 1440 760 1500H520C450 1320 560 1170 530 1040Z" fill="#d7aa7d"/>
      <path d="M110 360l180 20M70 620l230 50M120 920l215 20M1040 760l160-25M1000 1130l200-60" stroke="#d3926a" stroke-width="9" opacity=".45"/>
    '''),
    ("海岸静下来", "#687d88", '''
      <circle cx="850" cy="290" r="95" fill="#f0dfb8"/>
      <circle cx="890" cy="260" r="90" fill="#6e828b"/>
      <path d="M0 670H1200V1500H0Z" fill="#436d7e"/>
      <path d="M0 930Q440 800 1200 910V1500H0Z" fill="#285567"/>
      <path d="M0 1500V1000Q190 920 240 800Q320 750 420 820Q560 890 540 1000Q520 1150 790 1270Q980 1360 1200 1335V1500Z" fill="#c5b99a"/>
      <path d="M0 1500V1120Q250 1020 330 890Q430 900 410 1030Q440 1210 650 1360Q730 1410 790 1500Z" fill="#777f70"/>
      <path d="M540 1000Q520 1150 790 1270Q980 1360 1200 1335" fill="none" stroke="#e1d7b8" stroke-width="11"/>
      <path d="M740 760h180M790 840h140M720 1040h320M850 1150h220" stroke="#9fb3b3" stroke-width="3" opacity=".55"/>
      <g fill="#e6ddc2" opacity=".7"><circle cx="230" cy="260" r="3"/><circle cx="490" cy="180" r="3"/><circle cx="670" cy="430" r="2"/><circle cx="1070" cy="490" r="3"/></g>
    '''),
    ("留住最后一束光", "#d5ad9f", '''
      <circle cx="600" cy="500" r="160" fill="#d57e60"/>
      <path d="M0 840 200 620 390 790 650 490 930 820 1200 600V1500H0Z" fill="#a88c8b"/>
      <path d="M0 1100 250 830 500 1000 760 720 1200 1020V1500H0Z" fill="#7d737e"/>
      <path d="M0 1270 160 1110 440 1270 710 1030 950 1170 1200 950V1500H0Z" fill="#515d6c"/>
      <path d="M0 1440Q350 1260 650 1390T1200 1250V1500H0Z" fill="#374b59"/>
      <path d="M550 605 650 490 740 620 665 584 630 604 604 565Z" fill="#d1b8ae"/>
      <path d="M810 1310Q930 1270 1050 1315" fill="none" stroke="#7d8b8d" stroke-width="3" opacity=".5"/>
    '''),
]


def main() -> None:
    if (ROOT / "content/collections.json").exists():
        raise SystemExit("A catalog already exists. This initial-setup generator will not overwrite your collections.")
    DEST.mkdir(parents=True, exist_ok=True)
    items = []
    for number, (title, sky, body) in enumerate(ART, 1):
        name = f"{number:02d}"
        (DEST / f"{name}.svg").write_text(svg(body, sky, number * 11), encoding="utf-8")
        items.append({"id": name, "file": f"images/slow-days-v1/{name}.svg", "title": title, "width": 1200, "height": 1500})
    catalog = {"collections": [{
        "id": "slow-days", "slug": "slow-days", "version": "v1",
        "title": "把日子，过慢一点", "subtitle": "暂别匆忙，去风景里停一会儿。",
        "creator": "PaidDrive 创作组",
        "description": "九幅安静的风景，留给生活里的片刻空白。这是 PaidDrive 的演示插画合集。",
        "price_cents": 1900, "currency": "CNY", "preview_count": 3, "items": items
    }]}
    (ROOT / "content/collections.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(items)} original placeholder illustrations and collection catalog.")


if __name__ == "__main__":
    main()
