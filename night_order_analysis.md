# Night Order — Cluster-Analyse

Nur **Townsfolk / Outsider / Minion / Demon** (Traveller, Fabled, Loric ausgeklammert).
Meta-Marker (DUSK / DAWN / MINIONINFO / DEMONINFO) als Strukturpunkte behalten.
Positionen stammen aus `nightsheet.json` (ThePandemoniumInstitute/botc-release).

---

## FIRST NIGHT (Pos 1 → 79, aufsteigend)

### █ [1] DUSK — Meta-Marker

### █ CLUSTER: EVIL-COORDINATION
*Warum hier:* Muss vor allem anderen laufen, damit Evil sich synchronisiert.

`6   [mini] Wraith` — kann Augen öffnen, wacht wenn andere Evils wachen

### █ CLUSTER: N1-DEMON-KILLS (Spezial-Demons)
*Warum hier:* Diese Demons töten schon N1 — läuft früh, bevor Red-Herring-Pool etc. gesetzt werden.

`7   [demo] Lord of Typhon` — killt N1
`8   [demo] Kazali` — wählt Minions + killt

### █ CLUSTER: N1-ABILITY-GAIN / SETUP_ONCE
*Warum hier:* Weist Abilities/Rollen zu — muss vor Minioninfo und vor allen Modifiern passieren.

`13  [mini] Boffin` — Demon bekommt Good-Ability
`14  [town] Philosopher` — wählt Ability (kann drunken)
`15  [town] Alchemist` — hat Minion-Ability

### █ CLUSTER: EVIL-KOMMUNIKATIONS-MODIFIER (vor Minioninfo)
*Warum hier:* Ändern *wie* Minions/Demon sich erkennen.

`16  [town] Poppy Grower` — blockt Minion/Demon-Info
`17  [demo] Yaggababble` — Secret Phrase → Todesfolgen später
`18  [town] Magician` — Demon denkt du bist Minion

### █ [19] MINIONINFO — Meta-Marker

### █ CLUSTER: BLUFF-/MINION-SETUP (zwischen Minioninfo und Demoninfo)
*Warum hier:* Läuft nach Minioninfo (braucht Minion-Kontext) aber vor Demoninfo (modifiziert was Demon sieht).

`20  [outs] Snitch` — 3 Bluffs pro Minion
`21  [outs] Lunatic` — denkt Demon zu sein
`22  [mini] Summoner` — 3 Bluffs + auf N3 macht er den Demon

### █ [23] DEMONINFO — Meta-Marker

### █ CLUSTER: POST-DEMONINFO SETUP
*Warum hier:* Nach Demoninfo — setzt weitere States, die vor Modifier-Block liegen müssen.

`24  [town] King` — Demon *lernt* dass du King bist
`25  [town] Sailor` — Drunk-Token platzieren
`26  [mini] Marionette` — denkt Good zu sein
`27  [town] Engineer` — *wählt* welche Minions/Demon in play
`28  [town] Preacher` — Minion-Ability-Entzug
`29  [demo] Lil' Monsta` — Minions wählen Babysitter

### █ CLUSTER: MODIFIER_POISON / DRUNK (Kern-State-Change)
*Warum hier:* Poison muss **vor** Info-Gathering laufen — sonst bekommen Townsfolk nicht die falsche Info.

`30  [demo] Lleech` — poisont Host dauerhaft
`31  [mini] Xaan` — Night-X Massen-Poison
`32  [mini] Poisoner` — **der Kern-Modifier**
`33  [mini] Widow` — sieht Grimoire + poisont
`34  [town] Courtier` — 3-Tage-Drunk
`35  [mini] Wizard` — Once-per-Game Wunsch
`36  [town] Snake Charmer` — Demon-Swap + Poison
`37  [mini] Godfather` — "You start knowing" Outsiders (Info-Position)
`38  [mini] Organ Grinder` — Secret-Vote-Regel + Self-Drunk

### █ CLUSTER: MODIFIER_VOTE / MADNESS
*Warum hier:* Setzt Vote/Execute-Bedingungen für morgen.

`39  [mini] Devil's Advocate` — Execute-Schutz morgen
`40  [mini] Evil Twin` — wechselseitige Identität
`41  [mini] Witch` — Nominate=Death-Curse
`42  [mini] Cerenovus` — Madness-Kommando
`43  [mini] Fearmonger` — Vote-Trigger
`44  [mini] Harpy` — Madness morgen
`45  [mini] Mezepheles` — Secret Word → konvertiert
`46  [demo] Pukka` — poisont & tötet (laufender State)

### ⚡ BRUCH: SETUP/ROLE-ASSIGNMENT (zwischen Modifier und Info)
*Warum hier:* Weisen Tokens zu, die Info-Chars später lesen.

`47  [town] Pixie` — lernt 1 Townsfolk
`48  [town] Huntsman` — kann Damsel umwandeln
`49  [outs] Damsel` — Minions erfahren Damsel in play
`50  [outs] Amnesiac` — unbekannte Ability

### █ CLUSTER: INFO_IDENTITY (Bluff-Token-Zuweisung, Kern-Info)
*Warum hier:* ST zeigt *physisch Token*. Läuft nach Poisoner (damit Drunk/Poisoned falsche Info bekommen), nach Red-Herring-Setup (Fortune Teller Pos 56 setzt Red Herring, wirkt also auch für sich selbst).

`51  [town] Washerwoman` — 1 von 2 ist Townsfolk
`52  [town] Librarian` — 1 von 2 ist Outsider
`53  [town] Investigator` — 1 von 2 ist Minion
`54  [town] Chef` — Evil-Pair-Count
`55  [town] Empath` — Evil-Neighbor-Count
`56  [town] Fortune Teller` — Demon-Check + **Red Herring setzen**

### █ CLUSTER: VOTE-CONSTRAINT (zwischen Info-Blöcken)
*Warum hier:* Setzt Tages-Constraint, nicht Info — darum außerhalb des Info-Kerns.

`57  [outs] Butler` — Vote-Constraint für morgen

### █ CLUSTER: INFO_IDENTITY (Fortsetzung)

`58  [town] Grandmother` — Good-Spieler + Character
`59  [town] Clockmaker` — Schritte Demon→Minion
`60  [town] Dreamer` — 2 Characters (1 korrekt)
`61  [town] Seamstress` — Same-Alignment

### █ CLUSTER: INFO_ALIGNMENT
*Warum hier:* Alignment-Info — läuft nach Char-Info weil Alignment durch Cult Leader/Mezepheles noch kippen könnte.

`62  [town] Steward` — 1 Good
`63  [town] Knight` — 2 Non-Demons
`64  [town] Noble` — 3 Spieler, 1 Evil
`65  [town] Balloonist` — anderer Character-Type
`66  [town] Shugenja` — Richtung zum nächsten Evil
`67  [town] Village Idiot` — Alignment-Info
`68  [town] Bounty Hunter` — 1 Evil-Spieler
`69  [town] Nightwatchman` — outet sich einem Spieler

### █ CLUSTER: LATE-ALIGNMENT-MUTATION / SPY
*Warum hier:* Ändern Alignment *direkt* oder lesen *alles*. Sitzt ganz spät damit finaler State gelesen wird.

`70  [town] Cult Leader` — wird Alignment eines Nachbarn
`71  [mini] Spy` — sieht Grimoire
`72  [outs] Ogre` — wird Alignment eines Spielers

### █ CLUSTER: GLOBAL-STATE-INFO (spätester Info-Block)
*Warum hier:* Liest den **finalsten** Spielzustand, nachdem alle anderen Abilities liefen.

`73  [town] High Priestess` — ST wählt „wichtigsten Spieler"
`74  [town] General` — Winning-Alignment-Einschätzung
`75  [town] Chambermaid` — zählt wer aufgewacht ist
`76  [town] Mathematician` — zählt abnormale Abilities *seit Dawn*

### █ [77] DAWN — Grenze zum Tag

### █ DAY-DEMON / SPECIAL (nach Dawn)
*Warum hier:* Operiert außerhalb der normalen Nacht.

`78  [demo] Leviathan` — Day-Demon, läuft nach Dawn
`79  [mini] Vizier` — Day-Execute-Spezial

---

## OTHER NIGHTS (Pos 1 → 99, aufsteigend)

### █ [1] DUSK — Meta-Marker

### █ CLUSTER: EVIL-COORDINATION

`4   [mini] Wraith` — Augen-Koordination

### █ CLUSTER: SETUP_ONCE / ABILITY-GAIN
*Warum hier:* Weist Abilities zu — muss vor Modifiern liegen.

`11  [town] Philosopher` — Ability-Gain (kann drunken)
`12  [town] Poppy Grower` — blockt Info bei eigenem Tod
`13  [town] Sailor` — Drunk-Token + Immortal
`14  [town] Engineer` — wählt Minions/Demon in play
`15  [town] Preacher` — Minion-Ability-Entzug

### █ CLUSTER: MODIFIER_POISON (Kern)
*Warum hier:* Poisoner-Block. Alles weitere hängt davon ab, wer poisoned ist.

`16  [mini] Xaan` — Massen-Poison
`17  [mini] Poisoner` — **Kern-Modifier**

### █ CLUSTER: MODIFIER_DRUNK + SETUP
`18  [town] Courtier` — 3-Nights-Drunk
`19  [town] Innkeeper` — Protection **+** Drunk (hybrid)
`20  [mini] Wizard` — Wunsch

### █ CLUSTER: SELF-KILL / CONDITIONAL-DEATH
*Warum hier:* Ihre Todes-Bedingung liest drunken/poisoned-State, den der Modifier gerade gesetzt hat.

`21  [town] Gambler` — stirbt bei falscher Guess
`22  [town] Acrobat` — stirbt wenn Target drunk/poisoned

### ⚡ BRUCH: PROTECTION (eigenes Cluster zwischen Modifier und Kill)
*Warum hier:* **nach** Poisoner (poisoned Monk wirkt nicht), **vor** Demon-Kill (sonst zu spät). Dataflow-Pflicht.

`23  [town] Snake Charmer` — tauscht mit Demon (funktional Protection)
`24  [town] Monk` — **pure Protection vs Demon**

### █ CLUSTER: MODIFIER_VOTE / MADNESS
`25  [mini] Organ Grinder` — Secret-Vote + Self-Drunk
`26  [mini] Devil's Advocate` — Execute-Schutz morgen
`27  [mini] Witch` — Nominate=Death
`28  [mini] Cerenovus` — Madness
`29  [mini] Pit-Hag` — Character-Change
`30  [mini] Fearmonger` — Vote-Trigger
`31  [mini] Harpy` — Madness morgen

### █ CLUSTER: TRANSFORMATION / CHARACTER-CHANGE
*Warum hier:* Vor dem Kill-Block — verändert *wer was ist* vor Killing-Resolution.

`32  [mini] Mezepheles` — Secret-Word-Konversion
`33  [mini] Scarlet Woman` — wird Demon wenn Demon stirbt
`34  [mini] Summoner` — macht Spieler zu Demon
`35  [outs] Lunatic` — denkt Demon zu sein

### █ CLUSTER: PRE-KILL-INTERRUPT (kann Demon-Kill blocken)
*Warum hier:* Läuft direkt vor Kill-Block weil Ergebnis Kill ersetzt oder verhindert.

`36  [town] Exorcist` — blockt Demon-Kill
`37  [town] Lycanthrope` — killt selbst + blockt Demon-Kill
`38  [town] Princess` — kippt Demon-Kill

### █ CLUSTER: REGISTER-AS / FALSE-IDENTITY
`39  [demo] Legion` — registers als Minion

### ⚡ BRUCH: KILL-BLOCK (der Kern)

### █ CLUSTER: DEMON-KILL (alle Demons gebündelt)
*Warum hier:* Herzstück der Nacht. Alles davor = Setup; alles danach = Reaktion.

`40  [demo] Imp`
`41  [demo] Zombuul`
`42  [demo] Pukka`
`43  [demo] Shabaloth`
`44  [demo] Po`
`45  [demo] Fang Gu`
`46  [demo] No Dashii`
`47  [demo] Vortox`
`48  [demo] Lord of Typhon`
`49  [demo] Vigormortis`
`50  [demo] Ojo`
`51  [demo] Al-Hadikhia`
`52  [demo] Lleech`
`53  [demo] Lil' Monsta`
`54  [demo] Yaggababble`
`55  [demo] Kazali`

### █ CLUSTER: MINION-KILL / SEKUNDÄRE KILLS
*Warum hier:* Nach Demon-Kill, weil sie *zusätzlich* killen.

`56  [mini] Assassin` — Once-per-Game garantierter Kill
`57  [mini] Godfather` — killt wenn Outsider starb

### █ CLUSTER: GOSSIP / TAG-TRIGGER-KILLS
`58  [town] Gossip` — Tag-Aussage → Kill heute Nacht

### █ CLUSTER: DEATH-REAKTION (reagiert auf Tod)
*Warum hier:* Diese Chars werden *durch Tod geweckt* oder *reagieren auf Tod* — müssen nach allen Kills sein.

`59  [outs] Hatter` — bei Tod → Demon/Minion-Reroll
`60  [outs] Barber` — bei Tod → Demon swappt 2 Characters
`61  [outs] Sweetheart` — bei Tod → 1 Drunk
`62  [outs] Plague Doctor` — bei Tod → ST bekommt Minion-Ability
`63  [town] Sage` — bei Tod durch Demon → 1 von 2
`64  [town] Banshee` — bei Tod durch Demon → neue Regel
`65  [town] Professor` — Resurrect-Versuch
`66  [town] Choirboy` — lernt Demon wenn King tot

### █ CLUSTER: SETUP/REVEAL-LATE (Damsel-Komplex & Amnesiac)
`67  [town] Huntsman` — kann Damsel verwandeln
`68  [outs] Damsel` — Minion-Guess-Knowledge
`69  [outs] Amnesiac` — Ability-Rätselraten

### █ CLUSTER: LATE DEATH-REAKTIONEN
`70  [town] Farmer` — bei Tod wird Good zum Farmer
`71  [outs] Tinker` — kann jederzeit sterben
`72  [outs] Moonchild` — reagiert auf eigenen Tod → kann noch killen
`73  [town] Grandmother` — stirbt wenn Grandchild killed
`75  [town] Ravenkeeper` — wacht wenn N1 getötet

### █ CLUSTER: INFO_IDENTITY (Info-Block)
*Warum hier:* Nach allen Kills/Transformationen/Reaktionen — liest finale Wahrheit.

`76  [town] Empath` — Evil-Neighbor-Count
`77  [town] Fortune Teller` — Demon-Check
`78  [town] Undertaker` — Execution-Char ← **muss nach allem, was Execution kippen kann**
`79  [town] Dreamer` — 2 Characters
`80  [town] Flowergirl` — Demon-voted?
`81  [town] Town Crier` — Minion-nominated?
`82  [town] Oracle` — Dead-Evil-Count
`83  [town] Seamstress` — Same-Alignment
`84  [town] Juggler` — Guess-Trefferzahl

### █ CLUSTER: INFO_ALIGNMENT (späte Alignment-Reads)
`85  [town] Balloonist` — Type-Wechsel
`86  [town] Village Idiot` — Alignment-Info
`87  [town] King` — lernt 1 Char wenn Dead≥Living
`88  [town] Bounty Hunter` — lernt Evil-Replacement
`89  [town] Nightwatchman` — outet sich
`90  [town] Cult Leader` — wird Alignment eines Nachbarn
`91  [outs] Butler` — Vote-Constraint morgen
`92  [mini] Spy` — sieht Grimoire (finalster State)

### █ CLUSTER: GLOBAL-STATE-INFO (spätester Block)
`93  [town] High Priestess` — ST-Wahl
`94  [town] General` — Winning-Alignment
`95  [town] Chambermaid` — Woken-Count
`96  [town] Mathematician` — Abnormal-Abilities zählen

### █ CLUSTER: DAY-SPECIAL (kurz vor Dawn)
`97  [demo] Riot` — Tag-3-Spezialregel

### █ [98] DAWN — Grenze zum Tag

### █ DAY-DEMON
`99  [demo] Leviathan` — läuft nach Dawn

---

## Zusammenfassung der Phasen

| # | Phase | N1-Range | Nn-Range |
|---|---|---|---|
| 0 | Dusk | 1 | 1 |
| 1 | Evil-Coordination | 6 | 4 |
| 2 | N1-Setup / Ability-Gain | 7–18 | 11–15 |
| 3 | Minion-/Demon-Info-Meeting | 19, 23 | — |
| 4 | Post-Info Setup | 24–29 | — |
| 5 | Modifier (Poison/Drunk/Madness/Vote) | 30–46 | 16–31 |
| 6 | Transformation | — | 32–35 |
| 7 | Protection | — | 23–24 |
| 8 | Pre-Kill-Interrupt | — | 36–39 |
| 9 | Kill (Demon + Minion) | (nur N1-Demons 7–8) | 40–58 |
| 10 | Death-Reaktion | — | 59–75 |
| 11 | Setup/Role-Assignment (spät) | 47–50 | 67–69 |
| 12 | Info_Identity | 51–61 | 76–84 |
| 13 | Info_Alignment | 62–69 | 85–92 |
| 14 | Late-Alignment-Mutation / Spy | 70–72 | — |
| 15 | Global-State-Info | 73–76 | 93–96 |
| 16 | Dawn | 77 | 98 |
| 17 | Day-Demon / Special | 78–79 | 97, 99 |

## Die Kern-Regel

**Alles, was den Spielstate ändert, läuft vor allem, was ihn liest. Innerhalb der State-Änderung gilt: Setup → Modifier → Protection → Kill → Transformation → Death-Reaktion — weil jede Phase den Output der vorherigen als Input braucht.**
