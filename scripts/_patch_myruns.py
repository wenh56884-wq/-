import io

p = 'D:/qihang/app/routers/workflow.py'
s = io.open(p, encoding='utf-8').read()

old = """            rows = list(cur.fetchall())
    finally:
        conn.close()

    items = []
    for r in rows:
        status = str(r["status"])"""
new = """            rows = list(cur.fetchall())
            # 学生还要知道「有哪些流程可以申请」：没有这个清单，卡片只对
            # 已经玩过的人可见，新学生永远发现不了这个能力。
            cur.execute("SELECT `编号` AS id, `名称` AS name, `描述` AS description"
                        " FROM `工作流定义` WHERE `租户编号`=%s AND `是否启用`=1"
                        "   AND `是否需要审批`=1 ORDER BY `编号` LIMIT 20",
                        (ctx.tenant_id,))
            available = list(cur.fetchall())
    finally:
        conn.close()

    items = []
    for r in rows:
        status = str(r["status"])"""
assert s.count(old) == 1
s = s.replace(old, new)

old2 = """    return {"total": len(items), "items": items}


@router.get("/runs")"""
new2 = """    return {"total": len(items), "items": items,
            "available": [{"id": int(a["id"]), "name": a["name"],
                           "description": a.get("description")} for a in available]}


@router.get("/runs")"""
assert s.count(old2) == 1
s = s.replace(old2, new2)

io.open(p, 'w', encoding='utf-8').write(s)
print('backend ok')
