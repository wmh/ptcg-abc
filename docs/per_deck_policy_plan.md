# Per-Deck Policy 建置計畫

> **目標**: 比照官方 sample (`agents/dragapult/main.py` 的 `_policy()` 模式)，
> 為每個牌組撰寫完整的逐牌策略——每張牌在每個 context 都有明確的分數，
> 不依賴 generic 推論。
>
> **最後更新**: 2026-06-24 23:55 CST
> **下一 Agent 請先讀這份文件**

---

## 1. 官方 Sample 的模式拆解

官方 Dragapult sample (`_policy()`) 的核心結構：

```
_policy(obs_dict)
  ├── 前期狀態收集 (card_counts, field_counts, hand_counts, deck_counts…)
  ├── hand_score(id)             → 每張牌的「在手上值多少分」
  ├── attach_score(id, pkm, act) → 每張能量貼到每個 Pokémon 值多少分
  ├── main_option_proc(obs,dmg)  → 攻擊規劃 (plan_a, plan_b)
  ├── MAIN context dispatch:
  │   ├── PLAY   → hand_scores[o.index]
  │   ├── ATTACH → attach_score()
  │   ├── EVOLVE → 每張進化卡硬編碼分數
  │   ├── ABILITY→ 硬編碼
  │   └── ATTACK→ attack ID (搭配 plan_a)
  ├── Sub-context dispatch:
  │   ├── SWITCH/TO_ACTIVE        → 每張 Pokémon 硬編碼
  │   ├── TO_BENCH/TO_HAND       → hand_score()
  │   ├── DISCARD                → -hand_score() (負值)
  │   ├── DAMAGE_COUNTER         → HP 區間 + 牌 ID
  │   └── ATTACH_FROM            → attach_score()
  └── 選取邏輯 (sorted_scores, minCount/maxCount)
```

### 每張牌的處理模式

`hand_score(id)` 對 **每一張牌** 都有獨立 case：

```python
if id == Dreepy:
    if main_pokemon_count >= 3: score = 1000
    else: score = 18000
elif id == Drakloak:
    if can_evolve_dreepy: score = 20000
    else: score = 3000
elif id == Dragapult_ex:
    ... # 4 種情況
elif id == Fezandipiti_ex:
    ... # 3 種情況
elif id == Budew:
    ... # 2 種情況
```

**每一張牌的每一個分支** 都是人工根據 top pilot 行為設定的。

---

## 2. 我們需要做什麼

### 現狀

| 牌組 | 政策模式 | 完整性 |
|------|----------|--------|
| Dragapult | 官方 sample (`_policy()`) | ✅ 完整—有 hand_score/attach_score/plan_a/plan_b |
| Megastarmie | BasePolicy 子類 (abstract methods) | ⚠️ 有逐牌分數，但靠 generic dispatch |
| Alakazam | 舊式 self-contained Policy | ❌ 不完整，缺逐牌分數 |
| Trevenant | 舊式 self-contained Policy | ❌ 不完整 |
| Bellibolt / Typhlosion | 棄用 | 不理 |

### 需要做的事

**為每個 active 牌組寫一份等同官方 sample 的完整政策**，包含：

1. ✅ **完整的 `hand_score()`** — 每張牌（Pokémon、Trainer、Energy）都有分數
2. ✅ **完整的 `attach_score()`** — 每個 target 都明確定義何時該貼、何時不該
3. ✅ **攻擊規劃器** — 計算最佳攻擊+目標組合（`plan_a` / `_plan_attack()`）
4. ✅ **每個 context 的 dispatch** — 不要有「未處理 fallback 到 0」
5. ✅ **能量紀律** — 不過充、不亂貼（sample 的 `energy_count >= 2 → return -1`）
6. ✅ **獎勵卡感知** — 知道打死這隻換幾張獎勵卡

### 不必做的事

- ❌ 改造所有牌組共用同一份 code（各有各的邏輯）
- ❌ ML / imitation learning / 模型 rerank
- ❌ 每日自動化管線（至少現階段不需要）

---

## 3. 可行性評估

### 每個牌組的工作量

以 Dragapult sample 為基準：

| 元件 | 行數 | 難度 | 說明 |
|------|------|------|------|
| 狀態收集 | ~40 行 | 低 | card_counts、field_counts、hand_counts 等 |
| `hand_score()` | ~140 行 | 中 | 每張牌 2-5 個分支，需要理解牌的功能 |
| `attach_score()` | ~50 行 | 中 | 需要知道每個 Pokémon 需要多少能量 |
| 攻擊規劃 | ~60 行 | 高 | 核心策略：算傷害、弱點、獎勵卡 |
| MAIN dispatch | ~100 行 | 中 | PLAY/EVOLVE/ATTACH/ABILITY/ATTACK 的分數 |
| Sub dispatch | ~120 行 | 中 | SWITCH/TO_HAND/DISCARD/DAMAGE 等 |
| 選取邏輯 | ~20 行 | 低 |
| **總計** | **~530 行** | |

### 時間評估

| 牌組 | 評估時間 | 備註 |
|------|----------|------|
| **Megastarmie** | 3-4 小時 | 已經有 BasePolicy 版本，改寫成 sample 風格 |
| **Alakazam** | 4-5 小時 | 需要從零寫 hand_score + attach_score |
| **Trevenant** | 3-4 小時 | 同上 |
| **Dragapult** | ✅ 已完成 | 就是 sample 本身 |

### 關鍵瓶頸

1. **攻擊規劃器最難寫** — 需要 mod 傷害計算、弱點、效果免疫、boss拉起組合
2. **分數校準需要資料** — 設定 `Dreepy=18000` vs `Budew=30000` 需要從 divergence_decode 或 top pilot replay 驗證
3. **測試需要時間** — 每寫一個牌組要跑 check_agent + 至少 80 場 cabt

---

## 4. 建議執行方案：三階段

### Phase 1: Megastarmie（3-4 小時）

把現在的 `MegaStarmiePolicy(BasePolicy)` 改寫成 sample 風格的完整政策。

**為什麼先做 Megastarmie？**
- 已經有 BasePolicy 版本，功能完整
- 知道 keidroid（#1）的行為可以對照
- 是我們目前的主力牌組

**具體步驟：**
1. 保留 Cinderace Explosiveness 開局邏輯
2. 重寫 `hand_score(id)` 風格 — 每張牌獨立 case
3. 重寫 `attach_score()` — Ignition 只在 active Mega 當 finisher
4. 強化攻擊規劃 — Jetting Blow 擴散 + Nebula 穿透已經有了，但要 sample 風格的 plan_a
5. 補上 DAMAGE_COUNTER / DISCARD 等 sub-context

### Phase 2: Alakazam（4-5 小時）

從零寫 Alakazam 的完整政策。

**為什麼第二個？**
- 55% top-tier WR，是我們的 hedging 牌組
- 目前只有 674 分，潛力大

**需要先做的事：**
1. 下載 Alakazam top pilot 的 episodes（Elo ≥ 1150）
2. 用 `divergence_decode` 分析他們的行為
3. 根據資料設定分數

### Phase 3: Trevenant（3-4 小時）

Trevenant 單獎勵快攻，邏輯和 ex 牌組完全不同。

**需要先做的事：**
1. 分析 top 1 Debauchery 的行為（之前 divergence_decode 做過）
2. 把以前的 piloting fix 整合進完整政策

---

## 5. 與 BasePolicy 的關係

BasePolicy 仍然有價值——它提供了：
- ✅ `normalize_selection()` — 選取邏輯
- ✅ `legal_fallback()` — 安全網
- ✅ `PrizeTracker` — 獎勵卡感知
- ✅ `make_agent()` — agent entry point wrapper

但政策層面，**從 BasePolicy 的 generic scoring 改成 explicit per-card scoring**：
- BasePolicy 的 `score_attach()` 有 `should_fuel()` + `attach_priority()` generic 邏輯
- Sample 風格：直接 `if pokemon.id == Dragapult_ex: ... elif ...`
- BasePolicy 有 `score_play_poke()` abstract 讓子類填
- Sample 風格：在 `hand_score()` 裡直接寫每張牌的分數

**結論**：保留 BasePolicy 的 infrastructure（正常化、fallback、PrizeTracker、make_agent），但政策層面全部重寫成 explicit scoring。

---

## 6. 具體步驟（給下一 Agent）

### Step 1: 確認當前分數
```bash
venv/bin/kaggle competitions submissions pokemon-tcg-ai-battle
venv/bin/kaggle competitions leaderboard pokemon-tcg-ai-battle --download -p /tmp/lb
```

### Step 2: 讀 divergence data（了解 top pilot 行為）
```bash
# 對 megastarmie: divergence_decode vs keidroid
venv/bin/python tools/divergence_decode.py agents/megastarmie --archetype "Mega Starmie ex" --player keidroid --context MAIN
```

### Step 3: 改寫 Megastarmie 成 sample 風格
參考 `agents/dragapult/main.py` 的 `hand_score()` / `attach_score()` / `main_option_proc()` 模式，
改寫 `agents/megastarmie/main.py` 的 `MegaStarmiePolicy`。

**關鍵檔案：**
- `agents/dragapult/main.py` (參考範本，~900 行)
- `agents/megastarmie/main.py` (要改寫的目標，~374 行)

### Step 4: 驗證
```bash
venv/bin/python tools/check_agent.py agents/megastarmie   # 必須 0 over-fill, 0 crash
venv/bin/python tools/cabt_eval.py agents/megastarmie dragapult 20  # 快速回歸檢查
```

### Step 5: Build + Submit
```bash
CG_LIB_PATH="$(pwd)/docs/official/models/cg-lib/cg" bash agents/megastarmie/build_submission.sh
venv/bin/kaggle competitions submit ... -m "megastarmie full policy v4"
```

---

## 7. 成功標準

| 指標 | 目前 | 目標 |
|------|------|------|
| Megastarmie 分數 | 757.0 (v2) / PENDING (v3) | >900 |
| hand_score 完整性 | 有逐牌分數但依賴 generic | 每張牌獨立 if/elif |
| attach_score 完整性 | 有 override 但用 should_fuel | 每個 target 明確分數 |
| 攻擊規劃 | 有 `_dmg()` + `_jett_ko_bench()` | 完整 plan_a (attack + target) |
| DAMAGE_COUNTER | 用 BasePolicy 的 `score_spread_target()` | 自訂 HP 區間 + 進化基底優先 |
| 選取邏輯過濾負分 | 有（BasePolicy normalize_selection） | 確保 UNNECESSARY 不會被選 |
| Alakazam 上線 | 674.6 | 完成 full policy → 預期 >800 |
| Trevenant 上線 | 911.5 (歷史) | 完成 full policy → 維持 >900 |

---

## 8. 彙總（給快速理解的 Agent）

**一句話**：為每個牌組寫一份像 `agents/dragapult/main.py` 那樣的完整 `_policy()`，
每張牌在每個 context 都有獨立分數，不靠 generic 推論。

**優先順序**：Megastarmie → Alakazam → Trevenant

**時間估計**：每個牌組 3-5 小時

**不做的**：ML、每日自動化、跨牌組共用政策邏輯（infrastructure 仍共用）
