# Vergelijking van ondertitelzoeken — 11 oktober 2026

Aanvulling voor versie **2.9.26**: de OpenSubtitles-API kan bij een zoekopdracht
naar een filmtitel en jaar ook ondertitels van andere films teruggeven. Bij
*The Peanut Butter Solution* kreeg Subtitle Suite daardoor 116 Nederlandse
kandidaten, terwijl de zoekopdracht met de filmcode niets opleverde. De nieuwe
controle verwijdert resultaten met een andere filmcode of titel. Alleen als er
geen filmcode beschikbaar is, wordt ook het jaar vergeleken. Een gecontroleerde
match met het videobestand blijft toegestaan. Als er geen passende ondertitel
overblijft, toont Subtitle Suite geen zoekresultaten.

De OpenSubtitles-plugin herkent eerst welke film of aflevering wordt afgespeeld.
Subtitle Suite stuurde naar OpenSubtitles vooral een opgeschoonde bestandsnaam.
De filmcode, seizoen, aflevering en bestandsherkenning waren wel beschikbaar in
Subtitle Suite, maar werden door deze zoekfunctie niet gebruikt. Dat kon minder
of slechter passende resultaten opleveren.

Bij een recente zoekopdracht op Kodi stond bijvoorbeeld
`euphoria s03e01 andale` als zoektekst, terwijl ook een IMDb-code beschikbaar was.
De nieuwe zoekfunctie gebruikt die code. Als de code geen passende aflevering
oplevert, probeert zij de code als seriecode met seizoen 3 en aflevering 1.
Daarna kan zij zoeken op `Euphoria`, met het seizoen en de aflevering apart.

## Wat is overgenomen en verbeterd?

| Onderdeel | Voorheen in Subtitle Suite | Nu |
| --- | --- | --- |
| Film herkennen | Alleen titeltekst bij OpenSubtitles | IMDb-code; titel als terugvaloptie |
| Aflevering herkennen | Seizoen en aflevering werden niet doorgegeven | Aparte filters, met onderscheid tussen een afleveringscode en een seriecode |
| Kodi-informatie | Vooral bestandsnaam | Ook oorspronkelijke titel, serienaam, seizoen en aflevering uit Kodi |
| Bestandsherkenning | Niet gebruikt door OpenSubtitles; lezen via Kodi werkte niet altijd | Twee binaire leesacties van 64 KiB; zoeken op de OpenSubtitles-bestandscode |
| Beste resultaten kiezen | Provider hield vooraf alleen de populairste resultaten over | Grotere kandidatenlijst, eventueel een tweede pagina; daarna passendheid beoordelen |
| Betrouwbaar passende bestanden | Bestandsnaam kon de beoordeling tegenspreken | Een bevestigd bestand komt bovenaan en weegt zwaarder dan naamverschillen |
| Titel opschonen | Korte woorden en sommige taalnamen verdwenen | Korte titels en andere alfabetten blijven behouden; afleveringstitel en technische toevoegingen verdwijnen |
| Kwaliteit bij gelijke passendheid | Vooral populariteit | Menselijke vertalingen en betrouwbare uploaders krijgen voorrang |
| Verschillende bestanden bij één resultaat | Alleen het eerste bestand | Alle bestanden worden apart aangeboden |
| Volledige ondertitels | Onderscheid niet verwerkt | Ondertitels met alleen de buitenlandse dialoog worden overgeslagen |
| Tijdelijke zoekgegevens | Vooral bestandsherkenning en taal | Ook titel, filmcode, seizoen, aflevering en videopad tellen mee |

De limiet voor het **tonen** van resultaten blijft de bestaande gebruikersinstelling.
Er worden minimaal 120 kandidaten per provider gevraagd voordat Subtitle Suite
de beste resultaten kiest. OpenSubtitles bekijkt maximaal twee pagina's per
zoekmethode en maximaal zes zoekaanvragen. Een gevonden passend bestand blijft
beschikbaar als een volgende zoekmethode tijdelijk mislukt. Extra aanvragen
respecteren annuleren en de bestaande tijdslimiet.

Het uitzendjaar van een aflevering wordt niet als startjaar van de serie
doorgegeven. Seizoen 0, voor speciale afleveringen, blijft een geldige zoekwaarde.
Voor Portugees en Chinees worden de taalvarianten van de huidige API gebruikt.

## Bronnen

- [De door de gebruiker genoemde OpenSubtitles-plugin](https://github.com/opensubtitles/service.subtitles.opensubtitles_by_opensubtitles/blob/master/service.py),
  met de [zoekfunctie in OSUtilities.py](https://github.com/opensubtitles/service.subtitles.opensubtitles_by_opensubtitles/blob/master/resources/lib/OSUtilities.py):
  combineren van bestandsherkenning, IMDb-code en titel; passende bestanden voorrang geven.
- [De huidige OpenSubtitles.com-plugin](https://github.com/opensubtitles/service.subtitles.opensubtitles-com/blob/master/resources/lib/subtitle_downloader.py):
  zoeken op codes, omgaan met serie- en afleveringscodes, en terugvallen op titel.
  Dit is ook de pluginfamilie die op deze Kodi-installatie aanwezig is.
- [De officiële huidige zoekparameters](https://github.com/opensubtitles/mcp.opensubtitles.com/blob/master/src/tools/search-subtitles.ts):
  onder andere IMDb-code, seriecode, seizoen, aflevering, jaar en bestandsherkenning.
- [Kodi's binaire bestandsinterface](https://github.com/xbmc/xbmc/blob/Omega/xbmc/interfaces/legacy/File.h):
  `readBytes()` levert binaire gegevens; `read()` levert tekst.

De technieken zijn opnieuw geïmplementeerd voor onze huidige API. De oude
Python 2-code en de oude XML-RPC-verbinding zijn niet overgenomen.

## Controle en status

De lokale controles gebruiken nagebootste Kodi-bestanden en providerantwoorden.
Ze controleren onder meer netwerkbestandsherkenning, terugvalopties, verkeerde
afleveringen, extra pagina's, dubbele bestanden, rangschikking en zoekgegevens.
De volledige lokale testsuite slaagt met 100 tests.

Versie **2.9.23** is op 11 oktober 2026 op de echte Kodi-installatie geïnstalleerd.
Kodi herkent deze versie en de geïnstalleerde programmabestanden komen overeen
met de lokale versie. De vorige plugin is bewaard als herstelkopie. De bestaande
instellingen zijn ongewijzigd.

De controles in Kodi zelf slaagden:

- De nieuwe code laadt in Kodi's eigen Python-omgeving.
- Bestandsherkenning via de echte Kodi-bestandsinterface geeft de verwachte code
  voor een gegenereerd testbestand.
- Inloggen op OpenSubtitles en echte zoekopdrachten werken.
- Euphoria S03E01 levert één Nederlandse en één Russische ondertitel op, evenveel
  als voorheen. De titelzoekfunctie vangt de onbruikbare IMDb-code op.
- Interstellar levert 12 Nederlandse en 39 Engelse kandidaten op.
- Een brede Engelse zoekopdracht op `Star Wars` haalt een tweede pagina op en
  geeft 95 kandidaten door voor beoordeling, tegenover 12 met de oude limiet.
  Deze brede opdracht bevat meerdere films en dient uitsluitend om het ophalen
  van meerdere pagina's te controleren.
- Een echte Nederlandse ondertitel is gedownload en op geldige SRT-tijden
  gecontroleerd. Het testbestand is apart opgeslagen en niet bij een film geplaatst.

De [controle-uitkomsten](validation/2.9.23-kodi.json) bevatten de exacte aantallen.
Het aantal beschikbare ondertitels blijft per film, aflevering en taal verschillen.
Afspelen en de timing van ondertitels tijdens een film zijn hierbij niet getest.
