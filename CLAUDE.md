# Pokémon TCG AI Battle Challenge — Project Guide

## 🔴 關鍵規則（Session 重啟時第一條）

1. **只提交版本當用戶明確說「提交」或「submit」**
   — 不可以自作主張 build + submit，即使你認為代碼是好的。
2. **每輪 Session 先讀這份文件的 Current status + 下方 doc 列表**
   — 確定目前做什麼、做到哪、什麼是廢案。
3. **每輪 Session 先讀 `docs/per_deck_policy_plan.md`**
   — 這是當前策略方針（比照官方 sample 寫每張牌的完整政策）。

Competition: **Pokémon TCG AI Battle Challenge** (Kaggle × The Pokémon Company × 松尾研 × HEROZ).
Goal: build an `agent(obs_dict)` that wins the standard-format card battle. Two tracks:
- **Simulation**: `pokemon-tcg-ai-battle` (Elo ladder, auto-battles). Deadline **2026-08-16**.
- **Strategy report**: `pokemon-tcg-ai-battle-challenge-strategy` ($240K). Deadline **2026-09-13**.
- 5 submissions/day; latest 2 are scored.

## Current status (2026-07-14 — v4 初讀不利→Lucario 敗局解剖→SHIPPED v4.1 rush-gate + v3 重跑（用戶「如擬」核准）)

- **7-14 SHIPPED 2/5（03:48 UTC）：v4.1（#54671175，Xerosic rush-gate）+ v3 重跑（#54671182，= 3c5caf3 舊牌表）。計分對 = 這兩支 = 同窗天梯 A/B（同起點 ~520、同時段、同低分池）。顯示分會暫跌到 ~600 幾天（772.5 的 7-08 v3 已被擠出計分對）— 這是刻意的：v4 排賽已枯竭（20 小時只 +1 場，凍在 616），等待零資訊；離 8-16 截止還 ~4 輪收斂週期。判定（兩支各 ≥100 場）：v4.1 > v3 重跑 → Majkel-60 反鏡像牌表+rush-gate 路線確認；v4.1 ≤ v3 重跑 → 新牌表在低分池結構性爬不動，退回 v3 牌表、鏡像成果只保留駕駛層。**

- **7-14 天梯：隊伍 772.5 / #1463 / 4979（= v3 重跑守住）。top-100 門檻 983.7（差 ~211）、top-1000 = 816、top-500 = 872。**
- **v4 A/B 初讀（51 場，未收斂但訊號負）：611.9 / WR 47.1%（近 40 場 42%）。新提交從 ~520 起爬，卡在 Elo ~612 / 對手池均值 625 的地下室。結構性困境：低分池 = Lucario 谷底（20% 場次、我們 2-8=20%），鏡像稀少（5 場，但 4-1 = 反鏡像包確實有效）— v4 的優勢池在 750+，爬不上去就兌現不了。**
- **7-14 Lucario 敗局解剖（Episode API 全 51 場 replay）：8 敗 = 4 場獎賽被輾（對手 10 回合拿 5-6 獎、我們 0-2；Mega Lucario 340HP+Cape 440 我們打不穿）+ 2 場 T2 donk + 2 場空板凳死。天梯 Lucario 牌表 ≈ agents/lucario_v3（多數 60/60）→ 差在駕駛。本地 A/B v4 vs lucario_v3 = 62.5%（120 場）vs 天梯 20% — cabt 打不出真人壓迫，勿當先知。**
  - **Majkel 贏 Lucario 的路徑（dump 2 場皆勝）：一口氣 KO Mega Lucario ex 拿 3 獎 ×2。Powerful Hand 是放指示物「不吃弱點」（已驗證卡片文本，代碼正確）→ KO 340 需 17 張手牌 = 抽爆牌庫；或 245 胡地 Psychic 吃弱點 ×2（對手 3 能量 = 320）。關鍵 = 每個補給位都要拿去抽牌。**
  - **漏洞定位：Xerosic 12800 > Hilda 12500 > Dawn 12000 — 對手手牌 ≥7 時永遠搶走抽牌位，vs Lucario（手牌無關快攻）純虧；每敗局實際燒 2-5 次。Nighttime Mine vs 非 Tera 也是死牌（低分未動）。**
- **v4.1 內容：Xerosic 加 `_opp_is_rush()` 對局閘門（RUSH_LINE_IDS = Lucario 線 673-678 在對手板面 → Xerosic 壓到 2500/800，抽牌優先）。鏡像行為 bit-identical（閘門在鏡像永不觸發）。驗證：check_agent PASS；鏡像 A/B 71%@120（= v4-vs-frozen 第三次取樣，前兩次 83/78，噪音內，毒藥測試過）；vs lucario_v3 64.0%@200（基準 62.5%，本地持平 — cabt bot 打不出天梯真人壓迫，真效果天梯驗）。**
- **下一步：(1) 每日查 v4.1 vs v3 重跑爬升軌跡（Episode API 或 submissions）；(2) 繼續 P1 鏡像挖礦（Majkel 655 場，池最大）；(3) 深挖 Lucario 駕駛可用舊 dump（7-07 有 Majkel vs Lucario 324 MAIN，舊牌表但目標選擇/排序可遷移）；(4) 空板凳/donk 4 敗提示 vs 快攻鋪場紀律 — 未動（鏡像挖礦說小板凳，動之前必須配對閘門）；(5) 恢復每日 autopsy。**

## Previous status (2026-07-13 — 盤點 + P1 完成 + SHIPPED Alakazam v4 Xerosic 反鏡像包（用戶「如擬」核准）)

- **7-13 SHIPPED 1/5（05:37 UTC）：Alakazam v4（#54634553）。計分對 = v4 + v3 重跑（#54449811, 767.9）= 天梯 A/B。下次查分（TW 08:00 後）：v4 若 > v3 重跑 → 反鏡像包路線確認，續挖；注意分數要 ≥100 場才算收斂讀數（860 教訓）。**

- **7-13 天梯讀數：隊伍 769.3 / #1501 / 4917（從 860.3/#657 大跌）。top-100 門檻 998.4（差 ~229）。**
  - **A/B 判定：v3 重跑（#54449811）= 769.3 / 175 場 WR 48.6%；v3.1（#54449798）= 754.5 / 161 場 WR 54.7%（但對手池偏低 Elo）。依預設規則 v3.1 < v3 → 守 v3；差距 ~1σ 屬噪音，兩者實力相當。**
  - **關鍵發現：7-07 的 860.3 是「未收斂高點」** — 該提交 Elo 軌跡 888→876→869→849（83 場即被換掉，一路下滑）；同一 agent 重跑 175 場收斂 = 769。**Alakazam v3 真實力 ≈ 770-800，860 從來不是真的。以後任何 <100 場的分數讀數都要打折。**
- **7-13 口袋池實測（Episode API 抓兩支共 336 場，Elo 700-850）：鏡像 18.8%/46%（7-11 單日 1/9！）、Lucario 16.4%/55%、Archaludon 15.8%/45%、Grimmsnarl 8.0%/41%、Cinderace 6.0%/45%、Crustle 5.4%/78%、Dragapult 5.1%/47%、Kangaskhan 4.5%/60%、Garchomp 3.9%/69%。三大失血（鏡像+Archaludon+Grimm ≈ 池 43%，全 <47%）。鏡像先後手無差（44/47%）、對手牌表新舊無差 → 純行中駕駛問題。敗局型態：Cinderace/Froslass 敗局短（93/62 步=被快攻輾），鏡像/Grimm 敗局長（160-168 步=僵持後輸）。**
- **7-12 頂級 meta（Elo≥1100, 2617 場）：Alakazam 44.9%/53.7% + Kangaskhan 28.9%/55.1% 雙頭壟斷；Grimmsnarl 退潮 10.0%。** **TR Mewtwo ex 8.6%/63.2% = 新最強反制（剋 Alakazam 64%/Kangaskhan 71%）**；Froslass 67.6%/2.0%；Dusknoir 5.5%（剋 Kangaskhan 73%）。
  - **新 #1 kashiwashira（1239.9）= TR Mewtwo 專武，dump 裡 451 場（63.2%）→ 最佳新牌組挖礦目標（牌表可直接抄+大量駕駛資料）。** #2 Yushin 雙修 Alakazam+Grimm；#3 Majkel 回歸純 Alakazam 655 場（鏡像資料充足）；#4/#5 = Kangaskhan（Budew 847 場）；#8 taksai = Froslass；#10 WinDecks = Dusknoir。vibechu 的 Slowking 已消失於前十 → 確認曇花一現。
- **優先序（7-13 盤點結論）：P1 鏡像駕駛挖礦（池最大+WR最低+Majkel 655 場資料就緒，篩 matchup=Alakazam）；P2 Archaludon 對局修正（53 場 45%，用 agents/archaludon gauntlet 驗證）；P3 評估 TR Mewtwo 新牌組（抄 kashiwashira 60+挖 451 場；先用口袋權重 gauntlet 驗證再決定）；P4 恢復每日 autopsy——5 天空窗 = 零新資訊，本次教訓。**

### P1 完成（7-13）— Alakazam v4「Xerosic 反鏡像包」（已提交 #54634553）
- **牌表換 Majkel 現役 60**（7-12 dump 556/655 場同表；**頂級 Alakazam 共識**：#2 Yushin 448/448、#6 bono 383/383、#7 Rmy、#9 matsurih 全跑同款）：+3 Xerosic's Machinations（對手棄到 3 手牌 = **鏡像鎖對方 Powerful Hand ≤60**）+2 Nighttime Mine（Tera 稅，剋 Dragapult ex）+1 Fez ex +1 Shaymin；砍 Battle Cage/2 Night Stretcher/1 Candy/1 Dunsparce/1 Dudunsparce/1 基本{P}。`divergence_decode.py` 新增 `--opp-archetype`（配對挖礦工具化）。
- **驗證：鏡像 A/B vs 凍結 v3.1（舊表）= 193W/47L = 80.4%（240 場，兩獨立 120 場 83%/78%）**；check_agent PASS；口袋 gauntlet 63.2%（vs v3 基準 69.4%，差異 = vs Lucario 57%（−15，牌表一致性代價）+ 鏡像線 46% 是「自我鏡像」假讀數——gauntlet 的 Alakazam 對手 = agents/alakazam 自己，真鏡像讀數以 A/B 80.4% 為準）。**口袋 EV：鏡像 18.8% 池 ×(+30pts) >> Lucario 16.4% ×(−15pts)，且頂級 45% 全是 Alakazam → 未來鏡像佔比只增不減。**
- **7-13 失敗實驗（毒藥偵測器又立功，全回退）**：照挖礦訊號做的「攻擊經濟學重定價」批次（ATTACK 6800+3×dmg 高於鋪場、Xerosic 壓到 6500、Dunsparce/Fez/Shaymin 降級）→ **鏡像 A/B 83%→28% 崩盤**；回退後逐項測 Pad 14000/Hammer 11000 也 −10pts（73-74%）。**教訓三度驗證：divergence 訊號（他 ATTACK 275x/Pad 134x/Hammer 119x）不保證贏——pointwise agree ≠ 實戰，每項改動必過 mirror A/B。最終版 = 純「換牌表+四張新卡政策」，主體分數一律不動。**
- 凍結的舊版對照組在 `agents/_ab_v3_frozen/`（untracked，= HEAD 的 v3.1 code+舊表，A/B 基準用）。

## Previous status (2026-07-08 — 體檢→挖礦→修正→SHIPPED 天梯 A/B 對（用戶預先授權「完成後直接推上天梯」）)

- **7-08 SHIPPED 2/5（04:44 UTC）：Alakazam v3.1（#54449798，Run Away Draw 排序修正）+ v3 原版重跑（#54449811，= 860.3 那份）— 計分對 = 這兩支 = 天梯實測 A/B。TW 08:00 查分：修正版若 ≥ 原版就採納續挖，否則 v3 守住分數。**
- **v3.1 內容（Majkel 7-07 配對挖礦，vs Grimmsnarl 1449 + vs Lucario 324 個 MAIN）**：板凳 Dudunsparce 的 Run Away Draw 15000→22000 = **回合內先抽 3 再做進化/鋪場決策**（他 ABILITY 157 vs 我們 43；我們的 EVOLVE:Dudunsparce/Kadabra 大量 over-pick 是晚抽的 cascade）。驗證：hold-out（Kangaskhan/Garchomp/mirror 5374 決策）MAIN 44→47%；**mirror A/B 120 場 55% 勝 v3**；口袋 gauntlet Lucario 65→73%（兩次獨立跑 73/75%）；check_agent PASS。
- **7-08 失敗實驗（都已回退，教訓再度驗證）**：(1) TO_ACTIVE 翻 Abra>Kadabra（依 16 個分歧點翻案**已量測過的**排序）→ mirror A/B 崩到 29% — **不要用小樣本分歧推翻註解裡寫明量測過的決策**；(2) EVOLVE:Dudunsparce 綁 draw 條件閘門 → 逐點 agree 退步（行為閘門必敗 3 連敗）；(3) 前排 Run Away Draw 放寬循環 → mirror 無改善。**新流程教訓：pointwise agree 升 ≠ 實戰贏，mirror A/B 是必跑的毒藥檢測器——本次靠它抓出 TO_ACTIVE 毒藥。**
- **7-08 基建**：`agents/archaludon`（口袋共識牌表，10/27 場相同，GenericPolicy）+ `cabt_gauntlet.py` FIELD 改口袋權重（Lucario 24/Archaludon 19/mirror 15/Grimm 8/Dragapult 6/Garchomp 5/Kangaskhan 3）。v3 口袋 gauntlet 基準 = 69.4%。
- **Majkel（#1）已分兵兩副牌：Alakazam 380 場 59% + Solrock/Okidogi 工具箱 258 場 57%**（7-07 dump）。他的 Alakazam 對 Dragapult 也只有 11%（1/9）→ 原型級剋制，別想修。Solrock 牌組對 Grimm 34%/對 Kangaskhan 76% — 是他的防 Kangaskhan 側翼。
- **下一步：(1) TW 08:00 查 v3.1 vs v3 天梯 A/B 讀數；(2) garchomp 對 Lucario 35%/Crustle 20% 的 nasuo 挖礦還沒做（他同牌 60%/50%，可挖但 garchomp 分數天花板低，優先度看 Alakazam 結果）；(3) 每日 autopsy。**

- **7-08 分數：Alakazam v3 = 860.3（新高）/ garchomp 首發 = 713.8（弱）。隊伍 860.3 / #657 / 4531（+8.8 分 / +76 名）。top-100 門檻 977.9（差 ~118）。** 頂端：Majkel1337 回到 #1（1151.3）；vibechu（Slowking）掉出前五 — 可能曇花一現，下次 autopsy 確認。
- **7-08 突破：Episode API 抓到我們自己的 142 場實戰**（每日 dump 只涵蓋 ~190 個頂級玩家，我們不在裡面）。方法見 memory `own_games_episode_api.md`：`ListEpisodes {submissionId}` + `kaggleusercontent.com/episodes/<id>.json`（要跟 301）。
- **7-08 體檢結論（詳見 memory `pocket_meta_lesson.md`）：**
  - **口袋 meta ≠ 頂級 meta**：Elo 700-900 的對手池是舊 meta — Archaludon ex ~19%（alakazam 池 30%！）、Mega Lucario ~24%、Alakazam 鏡像 ~15%、Dragapult ~6%、Crustle ~6%；Grimmsnarl 只有 ~3%。**gauntlet FIELD 權重要改成口袋配置；目前連 Archaludon 對手 agent 都沒有 — 要先建。**
  - **alakazam_v3 實戰 54%**（79 場）：Archaludon 62%、Lucario 53%、鏡像 57%、**Dragapult 1/7=14%（最大單點失血）**、Grimmsnarl 1/4。6 場 turn1-2 被 donk（孤 basic 開局手牌全死卡，救不了）— 條件 donk 率 8.7% vs Majkel 1.7%，差異=對手池（低分帶快攻 turn2 能打 70）非駕駛 bug，爬分自然消退，勿過度工程。
  - **garchomp 實戰 49%**（63 場）→ 713 的原因：**Lucario 6/17=35%、Crustle 1/5=20%**（ex 攻擊被鎖、20+ 回合僵死只拿 0-1 獎）、雜牌尾 0/5。nasuo445 同副牌對 Lucario 60% / Crustle 50% / Archaludon 67% → **駕駛差距，可再挖**（他 7-07 dump 有 690 場）。nasuo 對 Alakazam 鏡像僅 45%、對 Comfey 19%。
- **下一步：(1) 建 agents/_opponents/archaludon + gauntlet 權重改口袋配置；(2) alakazam vs Dragapult 修配對（六場敗局多為獎賽被輾，Battle Cage 有打但擋不住）；(3) garchomp 對 Lucario/Crustle 用 nasuo 對局 divergence-mine（篩 matchup）；(4) 每日 autopsy + 盯 Slowking 是否退潮。**

## Previous status (2026-07-06 — META 大翻盤盤點；megastarmie v2 + Alakazam-741 已提交（用戶「如擬」核准）)

- **7-06 SHIPPED 2/5：megastarmie piloting v2（09:36 UTC）+ Alakazam-741（09:36 UTC）— 最新 2 計分 = 這一對。等 TW 08:00（UTC 00:00）後查分：`venv/bin/kaggle competitions submissions pokemon-tcg-ai-battle`。**

- **7-06 盤點：我們停擺 11 天（最後提交 6-25），meta 在 6-28~7-01 全面翻盤。** 「夯」= 833.8 / #820 / 4354；**7-05 全天 0 場對局 — 不重新提交就不再排賽，分數凍結**。頂端壓縮：#1 Majkel1337 1243.9（用**非ex Alakazam 741線** = 我們 alakazam 牌表重疊 50/60）；rank 100 = 984.7（差我們 ~150）。keidroid 崩到 #2915。
- **新 meta（Elo≥1000, 7-05）：Grimmsnarl ex 38.6%/50.6% 新霸主、Alakazam-741 17.5%/52.3%、Kangaskhan ex 11.6%/56.9%（剋 Grimmsnarl 82%）、Cynthia's Garchomp ex 10.4%/60.1%（全場最高、剋兩大頭 → Phase 3 目標）。** 全是原有卡池被挖掘的牌組，本地 cg-lib 全認得（max id 1267）。詳見 memory `card_mechanics_reference.md` 新 meta 段 + `docs/strategy/牌組策略.md`。
- **megastarmie 沒死：#2 Yushin Ito（1172.6）牌表與我們 60/60 相同 → 純駕駛差。7-06 已 divergence-mine 他 7-04+7-05 共 ~5400 個 MAIN 決策，megastarmie 駕駛 v2 完成（未提交）**：小板凳（Poffin 只上 1 隻 Staryu, TO_BENCH agree 3→97%）、Turbo Flare 只拿板面需要的能量（ATTACH_TO 0→55%）、**DISCARD 反轉：先丟死卡訓練家/Ignition,保護水能量**（舊規則「先丟水」是錯的）、Wally 回血後重貼 1 水照樣攻擊、Hero's Cape 修 bug（工具被能量閘門擋住貼不到有能量的 Mega）、Hammer 加量（對 Grimmsnarl 也打）、狙擊進化基底（Abra>受傷 Kadabra）。Hold-out 7-05 全面改善（MAIN 55→59%）；check_agent PASS；鏡像 A/B 160 場 ≈49%（無退步）；新 gauntlet 87.6%（舊版 88.4%,同級）。
- **7-06 新對手池**：`agents/{grimmsnarl,garchomp,kangaskhan,ogerpon}` = 頂級玩家牌表 + GenericPolicy；`cabt_gauntlet.py` FIELD 已改成 7-05 top-tier 權重。
- **7-06 Phase 2 完成：alakazam 換 Majkel1337 牌表**（Dunsparce 305 版修正了本來就對應 305 招式 ID 的舊代碼、+1 Enriching、4th Alakazam/Candy/Enhanced Hammer、3 Night Stretcher、Battle Cage 4→1）**+ mine 他 7275 個 MAIN 決策**：板凳節制（線件≥3 停）、Candy 讓路 Kadabra 橋（Psychic Draw +3）、不疊板凳胡地（前排可以）、TO_HAND 抓線件不囤 Dudunsparce（50→57%）、TO_DECK 大方放回備用件（2→12%）、TO_BENCH Abra 優先（70→77%）、Battle Cage 留給 bench-damage 對局、Enhanced Hammer 見特能就打。**驗證：新 gauntlet 75.1% vs 舊 63.5%（vs Grimmsnarl 62→75%），新舊鏡像新版 68% 勝。** check_agent PASS。⚠ MAIN pointwise agree 45→42%（回合內排序 cascade 噪音，行為裁判以 gauntlet 為準）；⚠ 斬殺閘門實驗失敗已回退（手牌×20 中盤隨時「有斬殺」，把發展全壓死 → MAIN 33%）。**仍是 legacy 架構未遷 BasePolicy（check_agent 能量審核過,擇機再遷）。**
- **7-06 Phase 3 完成：`agents/garchomp` = GarchompPolicy（BasePolicy 子類）+ nasuo445 牌表,挖他 12693 個 MAIN 決策。** 核心規則（與 megastarmie 相反！）：**晚進化 Garchomp**（進化=失去 Gabite 的 Champion's Call+暴露 2 獎體,我們原本 over-pick 2466 次）、**大板凳**（受傷板凳餵 Spiritomb Raging Curse）、**setup 零鋪場**、狂輪轉（撤退0）、Boss 只留多獎 gust-KO、Lillie>Hilda。MAIN 42→51%/TO_BENCH 53→84%/SETUP 0→100%（hold-out 7-04 一致）。gauntlet 85.1%（vs Grimmsnarl 96%）；vs 我們 Alakazam 62% 勝 / vs megastarmie v2 34% 負。check_agent PASS（並修了 checker 誤把「貼工具給滿能量者」當 over-fill 的 bug）。**未提交。**
- **7-07 早盤分數：Alakazam-741 = 851.5（配對贏家）/ megastarmie v2 = 821.0（vs 6-25 舊版 839 未顯著超越，Elo 未收斂）。隊伍 851.5/#733/4429（+17.7 分/+87 名）。top-100 門檻 979.4。我們的對局尚未進 7-06 episode dump（只涵蓋 199 活躍玩家），逐對手體檢等 7-07 dump。**
- **7-07 Alakazam v3（用 7-06 新資料再挖 Majkel 10390 決策，未提交）：** (1) **Sacred Ash 修正**（TO_DECK 12→64%/hold-out 79%：從棄牌堆洗回時填滿 5 格線件，原本的保護條款只放 3 隻）；(2) **gust 目標用「可達手牌」判 KO-able**（Powerful Hand 抽到 11 張=220 → 拉 210HP 的 Ogerpon/Fez ex；中間形態 Morgrem/Gabite 拒進化 +350）；(3) TO_HAND 不再囤 Dudunsparce（引擎自己洗回牌庫；抓 Alakazam 線件，57→62%）；(4) Night Stretcher/Enhanced Hammer 加量。**A/B 直接對戰 851.5 上場版：62% 勝**；gauntlet 75.1% 持平；check_agent PASS。⚠ JIT-evolve 閘門實驗（拼圖留手上晚進化）量測退步（MAIN 43→38）已回退 — 與昨天斬殺閘門同教訓：**大的行為閘門在逐點指標上總是變差，只做局部排序修正**。
- **新 #1 vibechu（1195.3）= Slowking 工具箱**（Slowpoke/Slowking 162/163 + Kyurem/Annihilape/Conkeldurr/Latias/Kangaskhan 散件 + Academy at Night 1248 + Ciphermaniac's Codebreaking 1188）158 場 65% WR — 全新原型，盯。Majkel #2/Yushin #3/nasuo #4 都還在（我們挖的三個標竿=前四中的三個）。
- **7-07 SHIPPED 2/5（用戶指示「推上 kaggle 試試」，03:57 UTC）：Alakazam v3（#54414730）+ garchomp 首發（#54414739）。計分對 = 這兩支；megastarmie v2（821）與 Alakazam-741 首版（851.5）退出計分。**
- **下一步：(1) TW 08:00 查 v3 + garchomp 分數；(2) 用 7-07 episodes 做逐對手實戰體檢（我們的對局會出現在裡面）；(3) 每日 autopsy + 盯 Slowking（新 #1 vibechu 原型）。**

## Previous status (2026-06-25 — megastarmie Hilda no-Basic fix SHIPPED)

- **6-25 SHIPPED (用戶明確指示提交): `agents/megastarmie` — 修「無基礎緊急狀態」選牌 bug。** 實戰發現：手牌+板凳都沒基礎、場上只剩一隻 Mega Starmie 當前鋒時，agent 打 **Hilda**(只能搜進化、搜不到基礎)拿了張死卡 → 前鋒被 KO 直接輸。修法(只在 `basic_emergency` 觸發，不動正常分佈)：新增 `bench_body_count`/`basic_emergency` 旗標；**Buddy Poffin 20000 > Ultra Ball 18000(需 `safe_pitch_count()>=2` 才能安全棄 2 張) > Lillie 12000 ≫ Hilda 1500**；`score_discard` 保護 Lillie/Harlequin 不被自己的 Ultra Ball 丟掉。`check_agent` PASS(0 over-fill/fallback)。等 TW 08:00 後確認分數。
- **6-25 上午改寫的 `agents/megastarmie` = Sample-Style 2.0 全策略版**(per-card hand_score + 攻擊規劃器 + HP-zone DAMAGE_COUNTER + Turbo Flare 三道煞車防過量填能)。`megastarmie_v2` 是改寫前的 BasePolicy 薄子類舊版(保留比對用)。`megastarmie_pokepad` 測試分支已刪。
- **最新分數參考(6-24 提交)：megastarmie v3 871.5(最高) / v4 751.2 / v5 722.7；夯 757.0；Dragapult v3 636.7。** 歷史高點 1006（6/19 Alakazam）。
- **⚠ 提交紀律：只在用戶明確說「提交/submit」時才 build+submit（本次是用戶明確指示）。**
- **目前策略方針：為每個牌組寫「像官方 sample 一樣的完整政策」(`docs/per_deck_policy_plan.md`)。**
  - **不搞 ML / imitation learning / 自動化管線。**
  - **Phase 1: Megastarmie full policy（等用戶指示開始）**
  - Phase 2: Alakazam full policy
  - Phase 3: Trevenant full policy
- **`docs/imitation_learning_pipeline.md` 是廢案**（Agent 搞錯方向寫的），不要參考。
- **6-22 SHIPPED (5/5 subs USED). Latest 2 scored = `megastarmie` (#5, NEW) + Dragapult fix-v2 (778.5).** Scores accrue after next reset (UTC 00:00 / TW 08:00) — **CHECK THEM** (`venv/bin/kaggle competitions submissions pokemon-tcg-ai-battle`).
- **`agents/megastarmie/` — Mega Starmie ex + Cinderace (NEW 6-22, a CLONE of ladder #1 `keidroid`, Elo 1341.9 — huge gap to #2 ~930).** keidroid real-ladder (6-21, 116 games): **67% overall, vs Trevenant 76% / vs Dragapult 64% / vs Alakazam ~even** — it hard-counters the field's two biggest decks. Our pilot, after divergence-mining keidroid's games: **cabt vs our agents (80-game samples) = Dragapult 56% / Alakazam 56% / Trevenant 84%** — beats all three (earlier 66/68/85 were noisy 40-game reads; 40-game cabt swings ±~10pts, always confirm at ≥80). See the deck section below + memory `megastarmie_deck.md`. **NOT yet validated on real ladder — that's the only true judge (score at TW 08:00 6-23).** Refactored 6-23 onto the shared `BasePolicy` (see Repo layout); behavior-preserving (Trevenant matchup unchanged 84≈85) and `tools/check_agent.py` passes (0 over-fill/fallback).
  - **6-22 PILOT FIXES (divergence-driven, all measured vs keidroid):** (1) **IS_FIRST → go FIRST** (he's 27/27 — DECK-SPECIFIC, opposite of Dragapult's go-second); (2) **spread/`DAMAGE` targeting → snipe the opp's LOW-HP engine pieces** (Dunsparce/Phantump/Abra draw-engines & evolution bases), NOT a high-HP wall (Hop's Snorlax 150HP we can't KO) — agree **27%→99%**; (3) **Ignition Energy is a one-shot Nebula ENABLER, not build-up** (it is DISCARDED end-of-turn) → only attach it to an ACTIVE Mega that attacks THIS turn; **build with permanent Water** (Jetting Blow at 1 {W} is the workhorse) — this fix flipped Alakazam 50%→68%; (4) **DISCARD** dumps excess Water, NEVER the win-con (we were pitching Mega Starmie ex/Salvatore); (5) MULLIGAN→NO, handle EVOLVES_TO.
- **`agents/dragapult/` — Dragapult ex (PRIMARY).** Consensus top-tier netdeck. Phantom Dive spread/control. **PILOT = the official sample agent** with our robust scaffolding.
  - **6-22 PILOT FIX (divergence-driven):** `divergence_decode --archetype "Dragapult ex"` against Elo≥1150 pool revealed **Fezandipiti ex OVER-prioritization** was the #1 piloting bug. Fix (4 changes):
    1. **Fezandipiti ex PLAY score**: 53000→**35000** (was outranking Dreepy/Budew/Latias/items)
    2. **Fezandipiti ex hand_score (pre_ko)**: 50000→**15000** (TO_HARD no longer grabs Fez over energy+board)
    3. **Dreepy PLAY score**: 51000→**54000** (prioritize board setup)
    4. **ATTACH bonus vs Dragapult ex**: **+25000** when <2 energy (fuel Phantom Dive faster)
    - ⚠ KEY LESSON: **don't blindly increase EVOLVE scores** — making Dreepy→Drakloak evolve too attractive (50000) made the ATTACH-vs-EVOLVE divergence WORSE. EVOLVE stays at 30000, below ATTACH (45150) and ABILITY (40000).
- `agents/alakazam/` — Alakazam (AlakazamPolicy, **2nd deck / hedge**). Even vs Dragapult in the real meta (49%), 55.1% top-tier WR. Hedge.
- `agents/trevenant/` — Hop's Trevenant (TrevenantPolicy). **DEMOTED 6-22.**
- `agents/bellibolt/` (836) + `agents/typhlosion/` (532) — DEPRIORITIZED.
- **CRITICAL LESSON: local sims (ctypes + cabt) do NOT reliably predict ladder rank.** Still: REAL-LADDER A/B is the only judge — confirm at reset.
- **Daily limit**: 5 subs/day; latest 2 scored (displayed = best of the 2). UTC 00:00 = Taiwan 08:00 reset.
- **NEW TOOL**: `tools/autopsy.py` — one-shot daily pipeline: download episodes + leaderboard → run meta_analyze + divergence_decode → save reports to `/tmp/autopsy/<date>/`.

## Meta — re-check EVERY day with `tools/autopsy.py` (the meta flips fast)
**⚠ 7-06 SUPERSEDED: the entire section below is the OLD (6-21) meta — kept for trend only. Current meta = the 7-06 Current-status block above (Grimmsnarl/Alakazam-741/Kangaskhan/Garchomp) + `docs/strategy/牌組策略.md` + memory `card_mechanics_reference.md`.**
**6-21 episodes (5046 decisive games) — META FLIPPED AGAIN: Dragapult ex surged, Trevenant's WR cratered, Lucario extinct.**
TOP TIER (Elo≥1150, 1524 games):
- **Hop's Trevenant 42.2% / 52.3% WR** — still most-played at the top but WR collapsed from 64.6% (6-20). The field adapted.
- **Alakazam 18.9% / 55.1%** (our #2 — now a higher WR than Trevenant).
- **Dragapult ex 16.5% / 63.1% 🚀 (OUR NEW PRIMARY)** — the rapid riser; one consensus netdeck, 63% WR.
- Chandelure 6.0% / 66.7% 🚀, Cinderace 3.8% / 67.2% 🚀, **Mega Froslass ex 3.6% / 70.0% 🚀** (all Trevenant counters), Team Rocket's Mewtwo ex 1.9% / 75.4%, **Mega Lucario ex 0.4% / 46% (EXTINCT — was the 56% king).**
FIELD (all, 5046): Hop's Trevenant 37.6% / 51.9%, Alakazam 27.6% / 50.8%, Mega Lucario 16.6% / 35.8% (collapsing), Dragapult ex 6.4% / 61.5%.
**Dragapult matchups (row, top tier): vs Trevenant 79% ✓, vs Chandelure 81% ✓, vs Iono 80% ✓, vs Alakazam ~49-51% (even), vs Mega Lucario 46%, ONLY clear loss vs Cinderace 36%.** Best-positioned deck in the format — beats the two biggest field decks.
- Lesson: deck choice dominates; the wave moved from Trevenant→Dragapult in ONE day. **Next threats to watch: Cinderace (Dragapult's counter, 67% WR rising) + Chandelure + Mega Froslass.** Trend: Trevenant top-tier WR 64.6%(6-20)→52.3%(6-21); Dragapult tiny→16.5%/63% top tier.

## Repo layout (reorganized 2026-06-18 — see README.md)
- `agents/_base/policy_base.py` — **SHARED `BasePolicy` (ABC) — the single source of truth for the generic, deck-agnostic piloting logic (2026-06-23).** Why it exists: agents are self-contained `main.py` files, so the scaffolding used to be COPY-PASTED per deck — a fix in one deck did NOT propagate, and new decks silently re-introduced solved bugs (e.g. energy over-fill). Now: the **generic ENERGY DISCIPLINE** (`should_fuel`/`can_attack`/`attach_helps`, derived from each attack's real cost — over-fill is impossible by construction), dispatch, sub-scorers, and the robust `agent()` wrapper live in the base and are INHERITED; **deck-specific decisions are `@abstractmethod`s** (incl. `go_first()` — the deck-specific first/second choice) so Python REFUSES to instantiate a subclass that forgets one. A new deck = a thin `BasePolicy` subclass implementing the hooks (see `agents/megastarmie/main.py` as the reference). The Kaggle/cabt loader appends the agent dir to `sys.path`, so the bundled sibling `policy_base.py` imports fine; `build_submission.sh` copies it into the tarball (dev uses a symlink to `agents/_base/`).
- `agents/<deck>/` — each ladder agent. Each: `main.py`, `deck.csv` (60 IDs), `build_submission.sh` (packs `main.py + deck.csv + policy_base.py + cg/`). **New deck → subclass `BasePolicy`** (NOT copy `alakazam/main.py`, which is the LEGACY self-contained style). Legacy agents (alakazam/trevenant) still have inlined scaffolding and have NOT been migrated yet.
  - **After building/changing any agent, run `venv/bin/python tools/check_agent.py agents/<deck>` — it asserts the universal invariants (no energy over-fill, no crashes/fallbacks, legal selections) and reports whether the agent is on `BasePolicy`.** This is the systematic guard against per-deck regressions.
  - `agents/dragapult` = **Dragapult ex (PRIMARY, 6-22)** — adopts the official sample pilot (NOT a `*Policy` class; it's the sample's `_policy()` + a robust `agent()` wrapper). `agents/megastarmie` = **Mega Starmie ex + Cinderace (NEW 6-22, clone of ladder #1 keidroid)** — a `MegaStarmiePolicy` written from scratch on the shared scaffolding, then divergence-tuned vs keidroid (cabt beats our Dragapult 66%). `agents/alakazam` = Alakazam (AlakazamPolicy, hedge). `agents/trevenant` = Hop's Trevenant (demoted). `agents/bellibolt`/`agents/typhlosion` = deprioritized.
- `docs/strategy/` — TC strategy write-ups. `web/` — human-vs-AI sandbox. `research/` — early/superseded experiments.
- `tools/`: `autopsy.py` (daily pipeline: download eps+LB → meta + divergence → `/tmp/autopsy/`), `meta_analyze.py` (episode zip → archetype distribution + WR + top-tier slice + matchup matrix; **run daily**), `replay_divergence.py` (replay top-pilot games through our agent → SelectContext-bucketed agree% = where we pilot differently), `divergence_decode.py` (same, but DECODES each disagreement into card/attack/option NAMES + aggregates human-vs-ours picks, and `--player "TeamName"` isolates ONE pilot — this is how you derive concrete piloting RULES, not just bare indices), `cabt_eval.py` (official-env eval vs sample bots — opponents now STALE: crustle/lucario/abomasnow are extinct), `cabt_ab.py` (A/B two of our agents), **`cabt_gauntlet.py` (run agent vs the REAL top-tier field, prevalence-weighted: Trevenant 41.5%→Mewtwo 0.9%)**, `check_agent.py` (**run after any agent change** — generic invariant checker: energy over-fill, fallbacks/crashes, BasePolicy structure), `battle_analyze.py` (anomaly/loss-cause report).
- **⚠ cabt is NOISY (±~10pts at 40g; use ≥80) AND still mispredicts the ladder** even with the composition-correct gauntlet — because our opponent PILOTS (our agents + GenericPolicy) are weaker than real top-100 humans. The gauntlet contradicted the known ladder result (rated `dragapult_nobonus` −2.2 though the ladder proved 871>778). **cabt is a regression-catcher/yardstick, NOT a strategic oracle; the ladder is the only true judge.**
- **`agents/_base/generic_policy.py`** — `GenericPolicy(BasePolicy)` + `make_generic_agent(deck_ids)`: turns any decklist into a competent cabt opponent (config auto-derived from card data; energy discipline inherited). `agents/_opponents/{chandelure,froslass,mewtwo}/deck.csv` = consensus high-WR lists pulled from episodes; `agents/_opponents/lucario_v3/` = the shared community Lucario pilot.
- **PrizeTracker (`policy_base.py`)** — adopted from the shared "1250 Starmie" agent. Deduces OUR prized cards (decklist − everything visible == prize set, only when it equals the prize count; conservative, returns None when ambiguous). Wired into `make_agent` (persists across decisions); BasePolicy exposes `self.is_prized(cid)` / `self.prized_count(cid)` / `self.copies_in_deck(cid)`. Verified: deduces the prize set ~83% of decisions on real games. First use: megastarmie skips Mega Signal when every Mega Starmie ex is prized (the search would whiff). **Available to ALL BasePolicy agents — add more uses (don't dig for prized pieces; plan around a prized win-con).**
- `docs/official/models/` — official notebooks + `cg-lib/` (local engine). **GITIGNORED** (on the Kaggle site); kept locally for testing. `.kaggle*/`, `private/`, `venv/`, `**/cg/`, `*.tar.gz` also gitignored.

## Build & submit (per agent)
```bash
CG_LIB_PATH="$(pwd)/docs/official/models/cg-lib/cg" bash agents/<agent>/build_submission.sh
venv/bin/kaggle competitions submit pokemon-tcg-ai-battle -f agents/<agent>/submission.tar.gz -m "message"
venv/bin/kaggle competitions submissions pokemon-tcg-ai-battle    # check score
```

## Analyzing the meta (episode replays)
Episodes (real ladder games incl. top players) are Kaggle datasets, one per day:
```bash
venv/bin/kaggle datasets download kaggle/pokemon-tcg-ai-battle-episodes-index -p /tmp/idx --unzip   # /tmp/idx/manifest.csv lists dates + top/median scores
venv/bin/kaggle datasets download kaggle/pokemon-tcg-ai-battle-episodes-2026-06-19 -p /tmp/ep19      # zip ~720MB (manifest's 21GB is the UNCOMPRESSED size)
venv/bin/kaggle competitions leaderboard pokemon-tcg-ai-battle --download -p /tmp/lb                # name→Elo for the top-tier slice
venv/bin/python tools/meta_analyze.py /tmp/ep19/<zip> --elo 1150                                     # archetype distribution + matchups
venv/bin/python tools/replay_divergence.py /tmp/ep19/<zip> agents/alakazam --archetype Alakazam      # piloting divergences
```
Process the .zip directly with Python `zipfile` (do NOT extract — 21GB unpacked). Each episode JSON: `steps[1][pi]['action']` = the 60-card deck; `rewards` = [p0,p1] (winner = higher); `info.Agents[i].Name` = player (map to Elo via the leaderboard CSV's `TeamName`). Replay: `steps[t][pi]['observation']` feeds our `agent`; the ANSWER to obs[t] is `steps[t+1][pi]['action']` (off-by-one — sub-decisions are consecutive same-pi steps; step-1 action is the deck).
Leaderboard: `venv/bin/kaggle competitions leaderboard pokemon-tcg-ai-battle --download`.

## Engine API essentials (cg-lib)
- Game-over: `obs.current.result != -1` (winner index). `obs.select is None` during deck-selection (return the 60 IDs).
- `SelectContext`: MAIN=0, SETUP_ACTIVE=1, SETUP_BENCH=2, SWITCH=3, TO_ACTIVE=4, TO_BENCH=5, TO_HAND=7, DISCARD=8, ATTACH_FROM=21, ATTACH_TO=22, DAMAGE_COUNTER=13/14, IS_FIRST=41, MULLIGAN=42.
- `OptionType`: NUMBER=0, YES=1, NO=2, CARD=3, ENERGY=6, PLAY=7, ATTACH=8, EVOLVE=9, ABILITY=10, RETREAT=12, ATTACK=13, END=14.
- `Pokemon`: `.hp` (current), `.maxHp`, `.energies` (list of EnergyType), `.energyCards`, `.tools`, `.id`.
- `EnergyType`: COLORLESS=0, GRASS=1, FIRE=2, WATER=3, LIGHTNING=4, PSYCHIC=5, FIGHTING=6 ...
- `State`: `.turn`, `.yourIndex`, `.firstPlayer`, `.supporterPlayed`, `.stadiumPlayed`, `.energyAttached`, `.stadium`, `.players[2]`.
- Card data: `all_card_data()` → `card.cardId/hp/weakness/resistance/ex/megaEx/stage1/stage2/attacks/skills/evolvesFrom/retreatCost`. `all_attack()` → `attack.attackId/name/damage/energies/text`.

## Testing: use the OFFICIAL cabt env (accurate), not the ctypes harness
`venv/bin/pip install kaggle-environments` (1.30.1 = ladder version), then:
```bash
venv/bin/python tools/cabt_eval.py agents/alakazam crustle 20   # <our_dir> <crustle|lucario|abomasnow|dragapult|mirror> [games]
```
`tools/cabt_eval.py` builds opponents from the sample notebooks + consensus decks and runs `make('cabt')` matches (~1s/game). The old ctypes loop (battle_start/battle_select) gives UNRELIABLE numbers for some matchups (it crippled the strong day-1 Crustle bot: ctypes 98% vs cabt 20% for the same matchup; mirror & Lucario agree). Trust cabt + the real ladder. Agents need `cg/` copied into their dir for cabt.

## Human-vs-AI web sandbox (`web/`)
Play against the agent in a browser and see the strategy's suggested move + per-option scores at every decision (for finding optimization points by comparing human intuition vs the agent).
```bash
venv/bin/python web/server.py        # then open http://localhost:8000
```
- You pilot the Typhlosion deck (`agents/typhlosion`); pick opponent (Crustle/Lucario) in the header.
- `web/server.py`: stdlib HTTP server wrapping the cg engine; runs the opponent agent automatically; exposes `/new?opp=`, `/state`, `/select`. The human's legal options are labelled and each shows `QuilavaPolicy.rank()` score; the AI's `normalize_selection` pick is flagged `recommended`/★.
- `web/index.html`: single-page board UI. Single global game, single-threaded (one user at a time — the cg engine has global state).

## Strategy reference docs (Traditional Chinese — for the user to review)
- `docs/strategy/牌組策略.md` — all deck strategies, meta distribution, rock-paper-scissors map, expected-WR table, deck-building checklist.
- `docs/strategy/訓練家牌應用.md` — every trainer card by category (draw/search, energy, disruption, heal/recover, switch, tools, stadiums) + application notes & combos.
Keep both updated whenever the meta shifts or we switch decks.

## Card mechanics reference
Full per-deck card/attack/ability details live in the agent memory file `card_mechanics_reference.md`
(`/home/wmh/.claude/projects/-home-wmh-workspaces-ai-projects-ptcg-abc/memory/`). **Update it on every deck change** — the user wants every deck's mechanics kept permanently.

### Dragapult ex (agents/dragapult — PRIMARY, 6-22) — consensus top-tier netdeck
- Pokémon: Dreepy(119, 70HP {N})→Drakloak(120, 90HP, *Recon Directive*: look top2, take 1)→**Dragapult ex(121, 320HP, stage2, 2 prizes)**. Support: Budew(235, 30HP {G}, *Itchy Pollen*[]=10 → opp can't play Items next turn), Fezandipiti ex(140, 210HP {D}, *Flip the Script*: if a mon was KO'd last turn, draw 3; Cruel Arrow[CCC]=100 to any), Latias ex(184, 210HP {P}, *Skyliner*: your Basics have no retreat cost; Eon Blade[PPC]=200), Meowth ex(1071, 170HP {C}, *Last-Ditch Catch*: on play from hand→search a Supporter). Energy: 4 Basic {R}/Fire(id 2) + 4 Basic {P}/Psychic(id 5).
- **Engine**: **Phantom Dive [R][P] = 200 to Active + put 6 damage counters (=60) on opp's BENCH however you like** — the win condition: set up multi-prize turns by pre-loading counters then KO-ing. Jet Headbutt[C]=70 is the cheap fallback. Disruption: **4× Crushing Hammer**(1120, coin-flip discard an opp Energy), Budew item-lock. Accel: **Crispin**(1198, search 2 diff-type basic energy: attach 1 + 1 to hand), **Rare Candy**(1079, Dreepy→Dragapult skip). Search/draw: Buddy-Buddy Poffin(1086, 2 basics ≤70HP→bench), Ultra Ball, Brock's Scouting, Poké Pad, Lillie's Det, Boss(1182), Night Stretcher, Unfair Stamp(1080, comeback draw after a KO), Lucky Helmet(1156 tool), Team Rocket's Watchtower(1256 stadium, {C} mons have no Abilities). **Plays GO SECOND.** Phantom Dive immune-active IDs {158,207,330,345}; no-counter IDs {28,199,203,207,362,1136} + holders of Mist(11)/Rock-Fighting(20) energy. Weakness: none on the line (Budew=Fire-weak).
- **Agent**: NOT a `*Policy` — it's the official sample's `_policy()` + a robust `agent()` wrapper. See the status section for why (sample beat a from-scratch policy 13-1).
- **6-22 PILOT FIX (divergence-driven)**: `divergence_decode` vs Elo≥1150 pool showed **Fezandipiti ex over-prioritization** was the #1 bug. Top players attach energy to Dragapult ex & play Dreepy/Budew/Latias/items over Fezandipiti ex. Fix: Fez PLAY 53000→35000, Fez hand_score(pre_ko) 50000→15000, Dreepy PLAY 51000→54000, ATTACH bonus +25000 when Dragapult ex <2 energy. ⚠ CRITICAL: EVOLVE score MUST stay at 30000 (raising it to 50000 made the ATTACH-vs-EVOLVE divergence WORSE). This is the lesson: every score change must be verified against the divergence data, not made intuitively. See divergence_data in `/tmp/autopsy/`.

### Mega Starmie ex + Cinderace (agents/megastarmie — NEW 6-22, clone of ladder #1 keidroid)
- Pokémon: Staryu(1030, 70HP {W})→**Mega Starmie ex(1031, 330HP, STAGE-1 megaEx, 3 prizes, {W})**; **Cinderace(666, 160HP, Stage-2 {Fire})** played WITHOUT its pre-evos via *Explosiveness* (may put it face-down in the Active Spot during setup → it opens like a Basic). Energy: 9 Basic {W}(id 3) + **4 Ignition Energy(id 17)**.
- **Engine**: Mega Starmie ex — **Jetting Blow [W] = 120 + 50 to 1 bench** (THE WORKHORSE; needs only 1 Water; keidroid's most-used attack) and **Nebula Beam [C][C][C] = 210, ignoring weakness/resistance AND any effects on opp's Active** (pierces Crustle-immunity / Mist / damage-reduction — universal hammer). Cinderace **Turbo Flare [C] = 50 + search 3 Basic Energy → bench** (T1 accel engine). **Ignition Energy provides {C}{C}{C} on an EVOLUTION mon but is DISCARDED end-of-turn** → it is a one-shot Nebula enabler, NOT build-up. Sustain: **Wally's Compassion(1229)** heal ALL dmg on a Mega ex + put its energy to hand (recycle), **Hero's Cape(1159)** +100HP → 430HP wall. Disruption 4× Crushing Hammer. Search/draw: Mega Signal(1145, find a Mega ex), Salvatore(1189, evolve a no-ability mon e.g. Staryu→Mega Starmie this turn), Buddy Poffin, Ultra Ball, Pokégear, Hilda, Lillie's Det, Harlequin, Night Stretcher, Boss. **Plays GO FIRST** (deck-specific; opposite of Dragapult). Weakness: Mega Starmie=Lightning, Cinderace=Water.
- **Agent**: `MegaStarmiePolicy` written from scratch on the shared scaffolding (no official sample exists), then **divergence-mined vs keidroid's 116 games** (`divergence_decode --archetype Cinderace --player keidroid`). The 5 measured fixes → cabt vs our agents 40/52/78 → **66/68/85** (Dragapult/Alakazam/Trevenant). See Current-status section for the fix list. Key piloting truths: **Jetting Blow (1 Water) is the default attack, not Nebula**; **Ignition only as an active-Mega Nebula finisher**; **spread snipes low-HP engine pieces, not high-HP walls**.

### Hop's Trevenant (agents/trevenant — counter-meta deck, DEMOTED 6-22)
- Pokémon (all SINGLE-prize, no ex): Hop's Phantump(878, 70HP {P})→**Hop's Trevenant(879, 140HP)**, Hop's Cramorant(311, 110HP), Hop's Snorlax(304, 150HP). Energy: 4 Mist(11, {C}+prevent effects on holder), 4 Telepath Psychic(19, {P}+search 2 basic {P} on attach). Trainers: Hop's Bag(1115), Pokégear(1122), TR Transceiver(1134)→Petrel(1219, any Trainer), Poké Pad(1152), **Hop's Choice Band(1171, −{C} cost +30 dmg)**, Boss(1182), Hilda(1225), Lillie's Det(1227), **Postwick(1255 stadium, +30 Hop's dmg)**, Secret Box(1092), Night Stretcher(1097).
- **Engine**: Trevenant **Horrifying Revenge** [C]=30, +100 if a Hop's was KO'd last opp turn (=130); with Choice Band it costs 0. Stack +30s (Postwick + Choice Band + **Snorlax "Extra Helpings" ability**, no self-stack) → 130+90=220. Cramorant **Fickle Spitting** [C]=120 only when opp at 3-4 prizes. Plan: flood cheap 1-prize bodies, trade UP into the opp's 3-prize ex, win the prize race. Weakness: Trevenant=Dark, Snorlax=Fighting (=Lucario, keep it benched).

### Lucario / Crustle (reference)
- **Mega Lucario ex = the field king (56%)** — megaEx, 3 prizes. Beat it by trading single-prize attackers up (Trevenant) or out-tempo (Alakazam, even matchup).
- Crustle (now rare): Dwebble(344)→Crustle(345), ability blocks ALL damage from ex/megaEx attacks. Immune-to-ex IDs {158,207,330,345}. Beat with non-ex attackers.

## Next steps / ideas
1. **Check the 6-22 scores next reset (THE key read)**: the latest-2-scored are **`megastarmie` (#5) + Dragapult fix-v2 (778.5)**. Did megastarmie's keidroid-clone land near the #1's tier? If it scores well it becomes a PRIMARY candidate; cabt says it beats our Dragapult 66% but **real ladder is the only judge**. Did the Dragapult Fez fix recover? Re-evaluate the primary based on both.
2. **Run `tools/autopsy.py` daily** — one command gives you fresh meta + divergence data. The meta flips fast (Lucario 56%→extinct in 3 days).
3. **megastarmie piloting headroom**: MAIN context is still only **38% agree** vs keidroid (lots of play-sequencing divergence). If the ladder read is good, the next pass mines MAIN: he plays Pokégear/Mega Signal/draw-search more, we over-play Buddy Poffin (partly curbed) and mis-sequence attaches. `divergence_decode.py agents/megastarmie --archetype Cinderace --player keidroid --context MAIN`.
4. **Watch CINDERACE / Mega Starmie ex (= our megastarmie clone, the keidroid line) + Chandelure + Mega Froslass ex** — Mega Starmie/Cinderace is the rising apex (beats both Trevenant AND Dragapult). If WE don't run it, it's our hardest counter. Pull its share daily.
5. **Alakazam piloting headroom**: archetype is 55% top-tier WR but our pilot scored only 674. No official Alakazam sample exists, so improve via divergence mining vs top Alakazam pilots (Elo≥1150). Hedge.
6. **When score-fixing any agent, NEVER blindly increase scores** — verify EVERY change against the divergence data. The EVOLVE 50000 mistake cost us 2 submissions to correct. Lower the over-prioritized card's score instead (e.g., Fez 53000→35000).

### Lessons learned 6-22 (megastarmie build — divergence mining a top HUMAN pilot from scratch)
- **A from-scratch `*Policy` CAN reach top-tier IF you divergence-mine the #1 pilot, not just intuit scores.** megastarmie went 40→66% vs our Dragapult from 6 *measured* fixes. The earlier "from-scratch loses 13-1 to the sample" lesson holds only for *un-mined* policies — the divergence loop is what closes the gap. When no official sample exists, **clone the #1 player's deck and `divergence_decode --player <name>`** their games.
- **`IS_FIRST` (go first/second) is DECK-SPECIFIC — always read it from the pilot data, never assume.** Dragapult goes second; Mega Starmie goes first (keidroid 27/27). Same for MULLIGAN.
- **Spread/snipe damage (`DAMAGE`/`DAMAGE_COUNTER`) should target the opponent's LOW-HP development pieces** (draw engines, evolution bases like Dunsparce/Phantump/Abra) to deny setup — NOT a high-HP wall you can't KO (we dumped 78 hits into a 150HP Snorlax). Rank targets by low current HP + a KO bonus, not by raw prize value.
- **Before optimizing energy attachment, identify the deck's ACTUAL win attack — it's often the CHEAP workhorse, not the flashy big attack.** Mega Starmie wins with Jetting Blow (1 Water), not Nebula Beam (CCC). Concentrating Water toward the 3-cost attack was wrong; the big attack is enabled on-demand by Ignition Energy. **Watch for end-of-turn-discard energies (Ignition): they are one-shot burst enablers for the turn you attack, never build-up — and never on a benched mon.**
- **A `DISCARD` scorer must hard-protect the win-con line** (we were pitching Mega Starmie ex / its evolve-enabler Salvatore to Ultra Ball). Prefer the most plentiful, cheapest resource (excess basic energy).
- **Sleep/special-conditions are engine-automatic**: the wake-up coin flip resolves inside the compiled cg engine (`manual_coin` off) — the agent is never asked to flip and only ever sees legal options, so robust scaffolding (`_legal_fallback`, 0-fallback) is all that's needed; no special handling.

### Lessons learned 6-23 (the over-fill recurrence → systematic prevention)
- **Root cause of "a bug fixed in one deck reappears in the next": the scaffolding was COPY-PASTED per `main.py`, so generic logic (e.g. energy discipline) was NOT inherited and a new deck could silently omit/break it.** I had even re-implemented over-fill prevention as a HARDCODED per-card `_fuel_goal` in megastarmie instead of the generic attack-cost rule — fragile by design.
- **Fix = a shared `BasePolicy` (ABC) at `agents/_base/policy_base.py`**: generic energy discipline (`should_fuel`/`can_attack`, derived from each attack's real cost — over-fill impossible by construction) + dispatch + robust `agent()` wrapper are INHERITED; deck specifics are `@abstractmethod`s (incl. `go_first()`) so Python refuses to load a subclass that forgets one. The Kaggle loader appends the agent dir to `sys.path`, so a bundled sibling `policy_base.py` imports cleanly (verified by extracting the tarball and loading in a clean dir). **New decks subclass it; do NOT hardcode energy goals — let `should_fuel` derive them.**
- **Plus a behavioral guard: `tools/check_agent.py`** runs ANY agent and asserts the invariants (no over-fill, no fallbacks/crashes, legal selections) — catches the bug class even in bespoke/legacy agents. Make it evolution-line-aware so pre-loading energy on a Basic that carries to a costlier evolution is NOT a false positive. **Run it after any agent change.**
- **cabt A/B at 40 games is NOISY (±~10pts)** — megastarmie read 66/68/85 at 40g but 56/56/84 at 80g (same agent). Never conclude regression-vs-improvement from a 40-game delta; use ≥80, and lean on the highest-signal matchup (here Trevenant, which was unchanged → confirmed the refactor was behavior-preserving).
- **Legacy agents (alakazam/trevenant/dragapult) are NOT yet on BasePolicy** — they pass `check_agent` today, but migrating them is the way to fully close this gap. Do it opportunistically when next touching one.
