# Campaign Simulation Roadmap

The desk is starting to become a game on purpose.

That does **not** mean it should become random, noisy, or cute at the expense of decision quality.

The simulation layer should do three jobs:

1. make the process easier to understand at a glance
2. make disciplined behavior feel rewarding
3. keep score in a way that reflects real operator quality, not fake dopamine

## The Town Model

The current dashboard now maps the desk into four town roles:

- Gatekeeper
  - handles approvals and refusals
- Quartermaster
  - manages daily risk budget and armed raids
- Merchant
  - watches long-term discount buys
- Archivist
  - keeps the brief, logs, and machine health intact

This is useful because each role maps to a real trading job.

The dashboard now has a first live `Inferno Town` layer:

- a village map
- clickable districts and focus cards
- tavern voices
- loot and relics
- moving villagers and ambient night-market motion

Those should always be derived from live desk state.

## The Quest Model

Every name should eventually appear as one of three quest types:

- Raid Quest
  - short-term earnings name that may actually be routed
- Scout Quest
  - interesting name that still needs proof
- Merchant Quest
  - long-term buy-the-dip candidate

The quest board should answer:

- what deserves attention right now
- what still needs proof
- what is a patient accumulation instead of a fast trade

## Inventory and Loot

Inventory should not be random.

It should be generated from the desk:

- raid writs from the top earnings quests
- merchant relics from long-term discount candidates
- forge sigils from approval-ready execution intents
- machine charms from healthy automation
- cracked relics when parts of the desk are stale or broken

This makes the game layer feel alive while still teaching what matters.

## Campaign Score

The campaign score should reward process quality, not fantasy.

Good things to reward:

- healthy automation
- fresh brief generation
- risk discipline
- approvals that match the real queue
- clean execution staging
- completed journaling

Bad things to punish:

- stale runs
- broken scripts
- overfilled risk budget
- missing journal entries
- broker-ready names with no human review

## Next Build Order

### Phase 1: Town and quest board

- campaign score
- live quest board
- town roles
- tie all of it to real desk data

### Phase 2: Trade journal becomes RPG history

- each real or paper trade becomes a run entry
- entries record thesis, route, risk, outcome, and lesson
- winning is not just PnL
- discipline and process adherence should also score points

### Phase 3: XP, gold, renown

- XP from following the system cleanly
- gold from realized paper or real outcomes
- renown from consistency over time
- penalties for revenge trading, rushed approvals, or off-system behavior

### Phase 4: Simulation settlement

- open quests populate a town board
- armed raids move to the gate
- merchant quests populate the vault
- resolved trades move into the archive hall
- loot accumulates in the inventory chest
- NPC dialogue reflects the live state of the desk

### Phase 5: Paper execution campaign

- every staged order becomes a paper battle
- compare expected move versus realized outcome
- rank setups by campaign performance

### Phase 6: Supervised broker surface

- thinkorswim stays the execution surface
- the desk prepares the ticket
- the operator still confirms the move
- no full auto until the campaign log proves edge

## Hard Rule

The game layer should never hide the trade.

If the user cannot still answer:

- what is the setup?
- what is the trigger?
- what is the risk?
- why now?
- what would invalidate this?

then the simulation layer is failing the desk.
