import io

p = 'D:/qihang/app/routers/interview.py'
s = io.open(p, encoding='utf-8').read()

old = '''@router.get("/jobs")
def job_candidates(keyword: str | None = None, city: str | None = None,
                   industry: str | None = None, pool: str = "national",
                   limit: int = 50, offset: int = 0,
                   ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """可练习的岗位池（默认全国 2931 条），支持关键词 / 城市 / 行业过滤与分页。

    返回真实 total（过滤后的总数），前端据此显示「共 N 个岗位」并做远程搜索。
    排序：有关键词时岗位名称命中优先；其余按编号升序（分页稳定、无随机）。
    """'''
new = '''@router.get("/jobs")
def job_candidates(keyword: str | None = None, city: str | None = None,
                   industry: str | None = None, pool: str = "national",
                   diverse: int = 0, limit: int = 50, offset: int = 0,
                   ctx: ToolContext = Depends(require_student)) -> dict[str, Any]:
    """可练习的岗位池（默认全国 2931 条），支持关键词 / 城市 / 行业过滤与分页。

    diverse=1：**行业分层抽样**——每个行业取编号最小的那个岗位作代表，按行业名排序。
    岗位表头部是成片的 IT 岗（种子数据的写入顺序），按编号取前 N 条会「看起来只有
    计算机岗」；分层抽样保证一屏里 82 个行业都在场。total 返回行业数（分层后的
    岗位数），前端据此提示。带 keyword 时不需要 diverse——搜索本身就覆盖全库。
    """'''
assert s.count(old) == 1
s = s.replace(old, new)

old2 = '''    order = " ORDER BY `编号` ASC"
    params_count = list(params)       # COUNT 只要过滤参数，不带 ORDER BY 的那个
    if keyword and pool == "national":
        order = " ORDER BY (`岗位名称` LIKE %s) DESC, `编号` ASC"
        params = list(params) + [f"%{keyword}%"]'''
new2 = '''    order = " ORDER BY `编号` ASC"
    params_count = list(params)       # COUNT 只要过滤参数，不带 ORDER BY 的那个
    if keyword and pool == "national":
        order = " ORDER BY (`岗位名称` LIKE %s) DESC, `编号` ASC"
        params = list(params) + [f"%{keyword}%"]
    elif diverse and pool == "national":
        # 行业分层：每个行业只留编号最小的代表岗。行业列有空白脏值，统一归到「其他」。
        industry_expr = "COALESCE(NULLIF(TRIM(`行业`), ''), '其他')"
        base += (" AND `编号` IN (SELECT MIN(`编号`) FROM `岗位`"
                 " GROUP BY " + industry_expr + ")")
        select += (", " + industry_expr + " AS industry_key")
        order = " ORDER BY industry_key ASC, `编号` ASC"
        params_count = list(params)'''
assert s.count(old2) == 1
s = s.replace(old2, new2)

io.open(p, 'w', encoding='utf-8').write(s)
print('backend ok')
