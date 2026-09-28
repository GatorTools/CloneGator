# CloneGator — consignes de travail

Duplication et sauvegarde de disques. Mode libre par défaut : l'opérateur
choisit ses disques à chaque opération. Mode station en raccourci : un réglage
enregistré d'emplacements source et cibles, pour une machine à baies.
Successeur de `clonesrv`, réécrit de zéro.

## Les deux documents font foi

- [ANALYSE-FONCTIONNELLE.md](ANALYSE-FONCTIONNELLE.md) — ce que le logiciel doit faire
- [PLAN-DE-DEVELOPPEMENT.md](PLAN-DE-DEVELOPPEMENT.md) — dans quel ordre on le construit

Ce sont des **documents vivants**. Quand une décision les contredit, les mettre
à jour — signaler la contradiction en une phrase, livrer, puis réécrire la
section concernée et ajouter une ligne au tableau de révisions. Ne jamais
laisser le code s'écarter d'une spec figée en silence, et ne pas employer le
vocabulaire de l'exception (« écart assumé », « contredit la spec »).

## Invariants

**P1 — La source d'une opération n'est jamais écrite.** Le maître d'un
clonage, le disque qu'on sauvegarde : lui et chacune de ses partitions passent
en lecture seule noyau pendant toute l'opération. Si une copie échoue ce n'est
pas grave ; détruire le maître l'est.

**P2 — Deux filets, et seulement deux.** Un disque utilisé par le système
(monté, swap, LVM, RAID, démarrage) n'est ni source ni cible : le noyau refuse
de l'ouvrir en exclusivité, c'est lui qui le dit. Un disque qui contient des
images CloneGator n'est jamais une cible. Tout le reste est le choix de
l'opérateur, sur l'écran de confirmation.

Les règles qui décident ce qu'un disque peut devenir — emplacement, mode,
filets de P2 — vivent **à un seul endroit**,
[clonegator/devices.py](clonegator/devices.py). Ne pas les dupliquer ailleurs,
ne pas ajouter de vérification par-dessus. Le moteur (`engine/`) ne regarde
jamais le rôle d'un disque.

Les autres principes (P3 à P6) sont au §2 de l'analyse.

## Contraintes techniques

- **Python 3, bibliothèque standard seule.** Aucune dépendance tierce, jamais
  de `pip`, jamais d'environnement virtuel. Si un besoin semble en réclamer
  une, le signaler plutôt que de l'installer.
- **Python orchestre, il ne copie pas.** Le travail réel est délégué aux outils
  système : `partclone`, `sfdisk`, `zstd`, `blockdev`.
- **Tout appel système passe par `clonegator/sysexec.py`.** Aucun autre module
  n'appelle `subprocess` ni ne lit `/dev`, `/sys`, `/proc` directement. C'est
  ce qui donne un délai d'attente sur chaque commande et le journal verbatim.
- **Ne jamais ouvrir la source en écriture, même pour la lire.** `parted` le fait
  pour un simple `print` : à chaque fermeture, udev croit le disque modifié et le
  re-sonde. L'ancien menu `clonesrv` a ainsi fait lire le port 1 en boucle
  pendant deux jours. Lire les tables avec `sfdisk --json` ou `lsblk`.
- **Désigner un disque par son emplacement** (`/dev/disk/by-path`), jamais par
  `/dev/sdX` : les noms changent quand on retire et remet les disques.
- **Pas de numéros de partition supposés contigus.** Une source en 1, 2, 3, 5
  est un cas normal, pas une anomalie.
- **Pas de garde-fou superflu.** Quand une règle structurelle couvre déjà un
  cas, la nommer et s'arrêter là. Ce projet démarre, il ne protège rien de
  critique, et une couche de sécurité de plus l'alourdit sans rien apporter.

## Langue

L'interface parle **anglais par défaut, et français** : tout ce que voit
l'opérateur passe par `t()` de [clonegator/langue.py](clonegator/langue.py), le
texte français servant de clé, et l'anglais vit dans
[clonegator/traductions.py](clonegator/traductions.py). Une phrase nouvelle à
l'écran = une entrée de plus au catalogue (un test le vérifie).

Tout le reste est en français : noms de variables et de fonctions,
commentaires, messages de commit, documents, et journaux techniques (leur
traduction est remise à plus tard). S'y tenir.

## Où on en est

Phases 1 à 7 terminées : le MVP est livré, le CloneGator live (ISO) aussi, et l'interface
est bilingue (anglais par défaut, français) et redessinée. Le mode PXE
(§17 de l'analyse) devient un projet séparé, GatorPXE, qui s'appuiera sur le live. `python3 -m clonegator` ouvre l'interface : mode libre
(sauvegarder, restaurer, cloner), mode station, journaux, partage réseau.
Reste un essai : un disque réellement usé pour SMART (plan, phase 4). Les
sous-commandes servent au développement.

```bash
python3 -m clonegator                              # l'interface
python3 -m clonegator inventaire                   # emplacements et disponibilité
python3 -m clonegator disques
python3 -m clonegator images                       # sauvegardes sur les disques USB
python3 -m clonegator cloner --source SATA1 --cibles SATA2 SATA3        # ÉCRASE
python3 -m clonegator sauvegarder Win11-labo --source SATA1
python3 -m clonegator restaurer <dossier> --cibles SATA2                # ÉCRASE
python3 -m unittest tests.test_emplacements tests.test_layout tests.test_fanout \
    tests.test_sante tests.test_interface tests.test_traductions tests.test_secours_ntfs tests.test_analyse \
    tests.test_clone_banc tests.test_images_banc
```

Journaux : `/var/log/clonegator/<date>_<opération>/` (avec `rapport.txt`) ;
réglages : `/etc/clonegator/clonegator.json`. Un seul CloneGator à la fois
(verrou dans `/run/clonegator`).

Phase 5 terminée, MVP livré. `./outils/construire-paquet.sh` construit le
`.deb` dans `dist/` (dépôt commité exigé). Publier : étiquette
`v<version>` (`~` → `-`, `+` → `.`), `gh release create --target <commit complet>` (l'abrégé est refusé), et joindre aussi une
copie nommée `clonegator.deb`, une copie de l'ISO nommée `clonegator-live.iso`, et l'archive du
démarrage réseau (`clonegator-live-pxe_<version>.tar`) avec sa copie `clonegator-live-pxe.tar`
— GatorPXE la prend là —, pour les adresses courtes
`github.com/GatorTools/CloneGator/releases/latest/download/clonegator.deb`.
Le dépôt APT (`GatorTools/apt`, copie locale `/root/GatorTools-apt`, publié à
`gatortools.github.io/apt`) reprend les trois dernières releases d'elle-même, chaque heure ;
pour publier tout de suite : `gh workflow run publier -R GatorTools/apt`.

## Site web

Le site n'est **pas** dans ce dépôt : il vit dans `GatorTools/GatorTools.github.io`
(copie locale `/root/GatorTools.github.io`), publié à `gatortools.github.io` ; les pages de
CloneGator sont sous `clonegator/`. Sa page Télécharger lit les releases GitHub au chargement :
publier une release suffit. Garder les textes courts, fidèles au logiciel, simples à lire.

## Le live

`./outils/construire-live.sh` (root) construit `dist/clonegator-live_<version>.iso` et
l'archive du démarrage réseau `dist/clonegator-live-pxe_<version>.tar` à partir du `.deb` du
commit courant. Ce qu'on ajoute au système
live vit dans `live/systeme/`, le menu de démarrage dans `live/grub.cfg`. La station A n'a pas
de virtualisation matérielle : QEMU tourne en émulation (`-accel tcg`), une minute pour
démarrer ; écran par `screendump` du moniteur, touches par `sendkey`.

## Essais

**Les baies sont le niveau d'essai principal.** Cinq SSD de 480 Go, sacrifiés :
un cycle y est assez court pour itérer. Pannes de cible provoquées par `/sys`
(`device/state` à `offline`, `device/delete`), sans rien débrancher.

**Le banc en boucle fabrique ce que les baies ne donnent pas** sans toucher au
maître du port 1 : sources aux numéros 1-2-3-5, GPT abîmée, cible plus petite
que la source. Ses disques n'ont pas de port, donc pas de rôle : ils servent aux
essais du moteur, qui reçoit des chemins. En ajouter quand on découvre un cas.

```bash
./outils/banc.sh creer
./outils/banc.sh etat
./outils/banc.sh detruire
```

`source-gpt.sha256` est le manifeste de référence : après un clonage, monter
la cible et relancer `sha256sum -c` dessus.

**Voir l'interface sans écran** : la lancer dans une session `tmux` détachée,
envoyer des touches (`tmux send-keys`), relever l'écran (`tmux capture-pane
-p`). La console physique se lit dans `/dev/vcs1` (sans les accents).

## Environnement

Le dépôt appartient à l'organisation GitHub **GatorTools** : `github.com/GatorTools/CloneGator`,
transféré du compte personnel `kevin-belanger` le 2026-09-28. Les anciennes adresses
redirigent, releases comprises : ne jamais recréer de dépôt `kevin-belanger/CloneGator`, il
capterait ces redirections. GatorPXE a son propre dépôt, `GatorTools/GatorPXE` (copie locale
`/root/GatorPXE`), qui ne contient encore que la description du projet. Le site de l'organisation vit dans son propre dépôt, `GatorTools/GatorTools.github.io`
(copie locale `/root/GatorTools.github.io`), publié à `gatortools.github.io` ; il porte les pages de
CloneGator.
Originaux des logos : `/root/visuels-gatortools/`.

Station de test sous Ubuntu 24.04, système sur disque USB, **root comme seul
utilisateur**. Le dépôt vit dans `~/clonegator`, soit `/root/clonegator`.

Les commandes disque exigent root : elles s'exécutent donc directement, sans
`sudo`, qui n'est pas forcément installé. Ne pas préfixer les commandes.

Les disques dans les baies sont des disques d'essai, sacrifiés par définition.

Partage réseau d'essai, créé par Kevin pour les tests : `//10.150.19.15/kevin`,
utilisateur `kevin`. Le fichier d'identifiants est hors du dépôt, lisible par
root seul : `/root/.config/clonegator-essais/partage-essai.cred`. Ne jamais
écrire le mot de passe dans le dépôt, un commit ou un journal.
