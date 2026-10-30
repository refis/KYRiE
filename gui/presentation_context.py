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
