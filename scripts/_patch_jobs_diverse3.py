import io

p = 'D:/qihang/app/routers/interview.py'
s = io.open(p, encoding='utf-8').read()

old = '''    elif diverse and pool == "national":
        # 行业分层：每个行业只留编号最小的代表岗。行业列有空白脏值，统一归到「其他」。
        # select 与 base 都已拼好，过滤条件必须各自追加（count 走 base+where）。
        industry_expr = "COALESCE(NULLIF(TRIM(`行业`), ''), '其他')"
        extra = (" AND `编号` IN (SELECT MIN(`编号`) FROM `岗位`"
                 " GROUP BY " + industry_expr + ")")
        select += extra
        select += (", " + industry_expr + " AS industry_key")
        base += extra
        order = " ORDER BY industry_key ASC, `编号` ASC"
        params_count = list(params)'''
new = '''    elif diverse and pool == "national":
        # 行业分层：每个行业只留编号最小的代表岗。行业列有空白脏值，统一归到「其他」。
        # 注意：select = 列清单 + base（FROM...WHERE），改列清单要插在 FROM 之前，
        # 过滤条件则追加到 base / select 尾部——顺序错了会拼出非法 SQL。
        industry_expr = "COALESCE(NULLIF(TRIM(`行业`), ''), '其他')"
        extra = (" AND `编号` IN (SELECT MIN(`编号`) FROM `岗位`"
                 " GROUP BY " + industry_expr + ")")
        head, sep, tail = select.partition(" FROM ")
        select = head + ", " + industry_expr + " AS industry_key" + sep + tail + extra
        base += extra
        order = " ORDER BY industry_key ASC, `编号` ASC"
        params_count = list(params)'''
assert s.count(old) == 1
s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8').write(s)
print('fixed2')
