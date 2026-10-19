# Sol: kilde- og varmepresisjon rettet

To smale endringer i eksisterende referanser: behold modellmålenes dokumenterte skala uten å legge til prosent eller nevner; beskriv varme som mulig bidrag når timing, arbeidslikhet og konkurrerende forklaringer ikke støtter en mer sannsynlig årsak.

Samme fire aktiviteter, spørsmål og vurderingskrav som holdout-runden ble kjørt med gpt-6.1-sol medium. Dette er nå regresjonstesting etter justering, ikke nye urørte testdata.

**Uavhengig kontroll: 4/4 førstesvar og 4/4 oppfølginger bestått. Begge målrettede feil er borte.** Algarve-svaret oppgir Difficulty 57 uten en 100-poengsnevner, og oppfølgingen sier at varme kan ha bidratt uten å rangere det som sannsynlig årsak. Positive rapporter, sykdomskontekst og fravær av SmO₂ håndteres fortsatt med relevante forbehold.

Ingen nye vesentlige tallfeil eller stoppefeil ble funnet i gjennomgangen. Mindre presisjonspunkter gjenstår i ordvalg om «målbar drift» fra variable vinduer, hvordan beina kjentes versus «tolererte» arbeidet, tidspunkt for CORE-maksimum og «pustebesvær». Se granskingen for konkrete formuleringer; bestått er ikke feilfri tekst.

Eksakt samtale videreført og opprinnelige testfiler uendret: 4/4. `git diff --check` bestod. Ingen aktivitets- eller planendringer. Skill-frontmatter er uendret; den tidligere påviste manglende PyYAML-avhengigheten i skill-validatoren ble ikke installert for denne referanseendringen.

Fire samtaler med én repetisjon per aktivitet er begrenset regresjonsevidens. Live-integrasjoner og kunstig sensorstøy er ikke testet. Alle oppfølgingsrapporter er syntetiske og ikke lagret som historiske treningsfakta. Granskeren hadde historikk fra tidligere runder, men fikk ikke skill-diffen.

- [Eksakt endring](source-heat.patch)
- [Svar og kommandoer](results-v2.json)
- [Uavhengig vurdering](independent-review-v2.json)
- [Opprinnelig holdout-resultat](results.md)

Fullt arkiv: `outputs/training-analysis-eval/2026-10-18-holdout-v2/`. CLI-brukstall bevares som rapportert; resume-tellere kan være kumulative.
