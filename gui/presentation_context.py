"""View-only recipient notes; observed actor IDs are not inferred callers or receivers."""


def presentation_context(row):
    kind=row.get('kind');packet=row.get('packet_id');actor=row.get('actor_id')
    result=dict(kind=kind,packet_id=packet,observed_actor_id=actor,
        player_context_required=None,automatic_timer_supported=False,cause_confirmed=False,
        observed_context=row.get('context'))
    if kind=='sound':
        result.update(actor_role='sound_origin',player_context_required=True,
            short='効果音のIDは音源です。受信者・配信範囲・呼出元は未確定。',
            summary='効果音の個体IDは音源の根拠で、再生を受けるプレイヤーのIDではありません。Aurigaのsoundeffectは接続プレイヤーを必要とします。既存の会話内生成と、NPCタイマーへの直接変換は別で、タイマー候補には追加しません。')
    elif kind=='music':
        result.update(actor_role='not_recorded',observed_actor_id=None,player_context_required=True,
            short='BGMの対象ActorIDは未記録。会話との同時観測だけではNPCへ割り当てません。',
            summary='このBGM通知は対象ActorIDを含みません。Aurigaのmusiceffectで再現する場合は接続プレイヤーが必要です。会話中に届いてもNPCの発生元・配信範囲を確定せず、タイマー命令へ変換しません。')
    elif kind=='achievement':
        result.update(actor_role='not_recorded',observed_actor_id=None,player_context_required=True,
            short='実績通知は対象ActorID未記録。プレイヤー向け観測でありNPC命令へは出しません。',
            summary='0x0A24は固定66バイトのうち表示定義どおり achievement_id@16 だけを保持します。他バイトは未解釈です。会話中に届いてもNPCの発生元とせず、achievement 実行命令やタイマーへ変換しません。')
    elif kind=='item_preview':
        result.update(actor_role='not_recorded',observed_actor_id=None,player_context_required=True,
            short='アイテムプレビューは対象ActorID未記録。所持Indexの観測メモでありgetitemへは出しません。',
            summary='0x0AB9（47バイト）／0x0B13（48バイト）は表示定義どおり index@2（生値-2）だけを保持します。他バイトは未解釈です。会話中に届いてもNPCの発生元とせず、getitem／itempreview 実行命令やタイマーへ変換しません。')
    elif kind=='navigation_active':
        result.update(actor_role='not_recorded',observed_actor_id=None,player_context_required=True,
            short='クライアントNavigation開始。対象ActorID未記録。viewpoint／warpと混同せずnavigateto実行命令は出しません。',
            summary='0x08E2（PACKET_ZC_NAVIGATION_ACTIVE、27バイト）は Type／SetType／Hide／MapName／xPos／yPos／sprIndex を保持します。rAthena navigateto→clif_navigateTo と対応しますが、会話中でもNPC発生元とせず、viewpoint（0144）や0092 warpと同一視しません。実行命令・タイマーへは変換しません。')
    elif kind=='map_property':
        result.update(actor_role='map_property',observed_actor_id=None,player_context_required=True,
            short='マップ属性通知です。対象ActorIDは未記録で、NPC本文命令へは出しません。',
            summary='0x01D6／0x099B／0x02E7はマップ種別・フラグ（または mapInfoTable）を保持します。カタログ外 type と flags は手動確認メモのみです。会話中に届いてもNPCの発生元とせず、mapproperty相当の実行命令やタイマーへ変換しません。')
    elif kind=='status_enter':
        result.update(actor_role='status_enter_target',
            short='入場時状態の対象IDです。0196／043F／0983のstatus付与とは別観測です。',
            summary='0x08FF／0x0984は対象ActorIDと effect_id／残時間／付加値を保持します。既存 status（sc_start相当）と混同せず、自動補完・実行命令・タイマー化はしません。コメント観測のみです。')
    elif kind=='mercenary':
        result.update(actor_role='mercenary_actor',
            short='傭兵表示の対象IDです。NPC復元の主経路外で、makemerc命令へは出しません。',
            summary='0x029Bは対象ActorID・名前・durationを保持します。他バイトは未解釈です。NPC本文の傭兵生成命令やタイマーへ変換せず、コメント観測のみとします。')
    elif kind=='progress_action' or kind=='progressbar' and packet==0x2f0:
        result.update(actor_role='not_recorded',observed_actor_id=None,player_context_required=True,
            short='進捗対象のActorIDは未記録。会話元NPCのIDと同一視しません。',
            summary='0x02F0は対象ActorIDを含まない進捗通知です。既存の会話内progressbarはプレイヤーの実行文脈で扱います。会話元IDを進捗対象へ流用せず、通知秒数をNPCのOnTimer値にも使用しません。')
        if row.get('comparison_scope')=='dialogue_owner':result['dialogue_owner_actor_id']=actor
    elif kind=='progressbar' and packet==0x9d1:
        result.update(actor_role='progress_target',short='対象ID付き進捗通知。対象IDは発生元NPCを示すとは限りません。',
            summary='0x09D1のActorIDは進捗対象の根拠です。発生元やプレイヤーの紐付け・実行命令を確定したものではありません。既存の観測・比較を維持し、未確認の命令やNPCタイマーへ変換しません。')
    elif kind=='viewpoint':
        result.update(actor_role='marker_npc',player_context_required=True,
            short='マーカー通知のNPC IDです。表示を受けるプレイヤーのIDとは区別します。',
            summary='0x0144のIDは参照Aurigaでは通知元NPCです。viewpointは接続プレイヤーに表示する命令で、同時観測だけでは受信対象・呼出元の条件を確定できません。会話内の既存生成条件を維持し、会話外や入力待ちの通知からNPCタイマーは生成しません。')
    elif kind in ('effect_value','effect_remove'):
        result.update(actor_role='effect_target',
            short='エフェクトの対象IDです。会話元・呼出元や配信範囲は別途確認が必要です。',
            summary=('0x0284は対象ID・エフェクトID・付加値を保持します。付加値の意味と再現命令が未確定のためコメントで残し、通常のmisceffectへ置き換えません。'
                     if kind=='effect_value' else
                     '0x0B0Dは指定個体のエフェクト解除です。会話元自身への既存delmisceffectと、外部NPCへの未採用候補を区別します。対象IDは呼出元や他ユーザーの関与を確定せず、会話外のタイマー採用には既存の手動確認が必要です。'))
    elif kind=='event_marker':
        result.update(actor_role='event_marker_target',
            short='イベントアイコンの対象IDです。起因NPC・OnTimer・表示条件は未確定です。',
            summary='0x0446は対象ActorIDと座標・state・kindを保持します。会話本文の単独はコメントのみ（OnQuestInfo関連付けは別経路）。手動タイマー採用と外部NPC候補の明示採用では showevent 実行命令候補を出します。起因・他ユーザー操作の混入は確定しません。')
    elif kind=='hat_effect':
        result.update(actor_role='hat_effect_target',
            short='帽子エフェクトの対象IDです。起因・装備条件・実行命令は未確定です。',
            summary='0x0A3Bは対象ActorID・enabled・effect_idを保持します。表示JSONの@hat_effect雛形とは別で、会話命令やNPCタイマーへ実行命令は出しません。コメント採用のみとし、hateffect等の未確認命令へ置き換えません。')
    elif kind=='colored_speech':
        result.update(actor_role='speech_source',
            short='色付きユニット発言の対象IDです。通常unittalkとは別観測で命令化しません。',
            summary='0x02C1は対象ActorID・color・textを保持します。表示JSONのwire色値を明示し、008D unittalkと混同しません。会話命令やNPCタイマーへ実行unittalkは出さず、コメント採用のみとします。')
    elif kind=='mapcell':
        result.update(actor_role='map_cell',observed_actor_id=None,
            short='マップセル変更の観測です。呼出元NPCのIDは含まれていません。',
            summary='0x0192の対象はマップ名・セル座標です。セル値をそのまま保持し、会話中でもNPCのsetcellやタイマーへ自動変換しません。観測窓への関連付けは同一取得・フロー・MAP世代と対象マップの一致が確認できる場合に限定します。')
    elif kind in ('dialogue_size','dialogue_position','dialogue_alignment'):
        result.update(actor_role='dialogue_layout',observed_actor_id=None,player_context_required=True,
            short='会話表示設定の通知です。対象IDは未記録で、会話元IDと同一視しません。',
            summary='サイズ・位置・整列の生値と受信時の会話状態を保持します。同じフローの会話は時間上の関連であり、呼出元の確定ではありません。会話開始比較では同じ開始根拠・MAP世代に限定し、会話に関連付く通知はmessize/mespos/mesalignを生成します。入力待ち中は既存方式で応答後へ配置し注意を残します。会話外・close待ちやNPCタイマーへは変換しません。')
    else:return None
    return result
