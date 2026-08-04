# Selate

Selate yra „Windows“ darbalaukio programa, skirta greitai išversti pasirinktą tekstą iš anglų į lietuvių kalbą. Ji veikia System Tray srityje, leidžia pažymėti tekstą pelės pagalba ir rodo vertimo rezultatą iššokusiame lange.

## Kas tai yra?

Selate padeda versti tekstą lokaliai jūsų kompiuteryje be poreikio perjungti programas ar rankiniu būdu kopijuoti informaciją. Darbo eiga labai paprasta:

1. Paleiskite programą ir palaukite kol inicijuosis vertimo modelis.
2. Laikykite Ctrl ir vilkite pelę per tekstą ekrane.
3. Programa užfiksuoja pažymėtą tekstą ir rodo vertimą iššokančiame lange.
4. Galite redaguoti vertimą, perkelti ar pakeisti lango dydį bei peržiūrėti ankstesnius vertimus iš meniu.

## Pagrindinės funkcijos

- Teksto pasirinkimas pelės pagalba naudojant Ctrl + vilkimas
- Vertimo langas su perkėlimo, dydžio keitimo ir redagavimo galimybėmis
- Integracija su sistemos dėklo piktograma
- Vertimų istorija iš dėklo meniu
- Pranešimų valdymas apie modelio būseną ir vertimo procesą
- Pasirenkamas paleidimas kartu su sistema ir „visada viršuje“ režimas
- Pirmojo paleidimo modelio atsisiuntimas ir vietinis modelio talpinimas

## Diegimas

### 1 variantas: paleidimas iš paruošto vykdomojo failo

Naujausia paruošta versija yra [dist/Selate.exe](dist/Selate.exe).

1. Eikite į aplanką dist.
2. Paleiskite failą Selate.exe.
3. Pirmą kartą paleidus, programa gali atsisiųsti vertimo modelį. Tai gali užtrukti priklausomai nuo interneto ryšio.

### 2 variantas: paleidimas iš šaltinio kodo

Reikalavimai:
- Windows 10 arba Windows 11
- Python 3.10+ (šiam projektui buvo naudojama Python 3.13 versija)
- Interneto ryšys pirmam modelio atsisiuntimui

Įdiekite priklausomybes:

```powershell
py -m pip install -r requirements.txt
```

Paleiskite programą:

```powershell
py main.py
```

## Naudojimo instrukcija

### Pagrindinė darbo eiga

1. Paleiskite Selate.
2. Palaukite, kol pirmą kartą bus paruoštas vertimo modelis.
3. Laikykite Ctrl ir vilkite pelę per tekstą, kurį norite išversti.
4. Vertimas pasirodo iššokančiame lange.

### Langų valdymas

- Perkelkite langą vilkdami jį pelės pagalba.
- Keiskite lango dydį už kampų arba kraštų.
- Dukart spustelėkite langą, kad jį redaguotumėte.
- Dešiniuoju pelės mygtuku uždarykite langą.
- Naudokite Ctrl + pelės ratuką teksto dydžiui keisti.

### Dėklo meniu

Dešiniuoju pelės mygtuku spustelėkite piktogramą dėkle, kad atidarytumėte meniu su:
- paleidimu kartu su sistema
- „visada viršuje“ režimu
- pranešimų nustatymais
- naudojimo instrukcijomis
- vertimų istorija
- programos perkrovimu arba išėjimu

## Sparčiųjų klavišų ir valdymo būdai

- Ctrl + vilkimas pele: pasirinkti tekstą vertimui
- Dukart spustelėjimas lange: redaguoti vertimą
- Ctrl + pelės ratukas: padidinti arba sumažinti teksto dydį
- Dešiniuoju pelės mygtuku ant dėklo piktogramos: atidaryti meniu

## Nustatymai

Nustatymai saugomi naudotojo profilyje, vietiniame programos duomenų aplanke.

Galima valdyti:
- paleidimą kartu su sistema
- „visada viršuje“ režimą
- pranešimų parinktis apie modelio ir vertimo veiksmus
- naudojimo instrukcijų rodymą

Šiuos nustatymus galite keisti iš dėklo meniu.

## Reikalavimai ir palaikomos platformos

### Palaikoma platforma
- Windows 10 / Windows 11
- rekomenduojama 64-bit sistema

### Paleidimo reikalavimai
- interneto ryšys pirmam modelio atsisiuntimui
- pakankamai vietos diske vertimo modeliui

## Priklausomybės

Projektas naudoja:
- pywin32
- uiautomation
- transformers
- torch
- sentencepiece
- pyinstaller

Šios priklausomybės yra nurodytos failą requirements.txt.

## Kūrėjų statybos instrukcijos

Norėdami sukurti Windows vykdomąjį failą:

```powershell
py -m pip install -r requirements.txt
py -m pip install pyinstaller
py -m PyInstaller --noconsole --onefile --name Selate --icon selate.ico --add-data "selate.ico;." --collect-all transformers --collect-all huggingface_hub --collect-all torch --collect-all sentencepiece --hidden-import win32api --hidden-import win32con --hidden-import win32gui --hidden-import win32event --hidden-import win32clipboard --hidden-import winerror --hidden-import pywintypes main.py
```

Paruoštas vykdomasis failas bus sukurtas aplanke dist.

Taip pat galima naudoti pagalbinį skriptą:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

## Projekto struktūra

- main.py: pagrindinis programos įėjimo taškas ir pagrindinė logika
- tray.py: dėklo piktograma, dėklo meniu ir pelės pasirinkimo kabliukai
- popup.py: vertimo lango sąsaja ir sąveika
- popup_draw.py: popup piešimo pagalbinės funkcijos
- popup_geom.py: lango dydžio ir padėties skaičiavimai
- popup_editor.py: vertimo teksto redagavimo funkcionalumas
- translator.py: modelio įkėlimas, atsisiuntimas ir vertimas
- clipboard.py: iškarpinės ir teksto pasirinkimo logika
- config.py: nustatymų saugojimas ir paleidimo registracija
- screen.py: ekrano ir monitorių geometrijos pagalbinės funkcijos
- tests/: regresiniai testai pagrindinėms funkcijoms
- dist/: sukompiliuotų vykdomųjų failų aplankas

## Žinomos ribotybės ir problemos

- Pirmo paleidimo metu gali užtrukti, kol atsisiunčiamas vertimo modelis.
- Programa yra skirta Windows sistemai ir priklauso nuo Windows specifinių API.
- Vertimo kokybė ir greitis priklauso nuo modelio ir kompiuterio galimybių.
- Kai kurios popup elgsenos gali būti tobulinamos ateityje.

## Ateities patobulinimai

Galimi ateities patobulinimai:
- papildomos kalbos
- geresnis veikimas be interneto
- patrauklesni popup animacijos ir stilius
- daugiau vertimų istorijos valdymo galimybių
- geresnė pakavimo ir diegimo patirtis

## Licencija

Kol kas licencija nepasirinkta. Jei planuojate platinti šį projektą viešai, rekomenduojama pridėti atitinkamą licenciją.
