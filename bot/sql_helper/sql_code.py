import math
from datetime import datetime

from bot.sql_helper import Base, Session, engine
from sqlalchemy import (
    Column,
    BigInteger,
    String,
    DateTime,
    Integer,
    or_,
    and_,
    case,
    func,
    text,
)
from cacheout import Cache

cache = Cache()


class Code(Base):
    """
    register_code表，code主键，tg,us,used,used_time,lv
    lv: 'b'=普通注册码, 'e'=公益注册码（默认）
    """

    __tablename__ = "Rcode"
    code = Column(String(50), primary_key=True, autoincrement=False)
    tg = Column(BigInteger)
    us = Column(Integer)
    lv = Column(String(1), default='e', nullable=True)  # 注册码等级类型
    used = Column(BigInteger, nullable=True)
    usedtime = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=True)  # 创建时间


Code.__table__.create(bind=engine, checkfirst=True)


def _migrate_add_code_lv():
    """迁移：若 lv 列不存在则自动添加（兼容旧版）"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='Rcode' AND COLUMN_NAME='lv'"
            ))
            if result.scalar() == 0:
                conn.execute(text(
                    "ALTER TABLE Rcode ADD COLUMN lv VARCHAR(1) NULL DEFAULT 'b' AFTER us"
                ))
                conn.commit()
    except Exception as e:
        print(f"【DB迁移】添加 Rcode.lv 列失败: {e}")


def _migrate_add_created_at():
    """迁移：若 created_at 列不存在则自动添加"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='Rcode' AND COLUMN_NAME='created_at'"
            ))
            if result.scalar() == 0:
                conn.execute(text(
                    "ALTER TABLE Rcode ADD COLUMN created_at DATETIME NULL AFTER usedtime"
                ))
                conn.commit()
    except Exception as e:
        print(f"【DB迁移】添加 Rcode.created_at 列失败: {e}")


_migrate_add_code_lv()
_migrate_add_created_at()


def sql_add_code(code_list: list, tg: int, us: int, lv: str = 'e'):
    """批量添加记录，如果code已存在则忽略"""
    now = datetime.now()
    with Session() as session:
        try:
            code_list = [Code(code=c, tg=tg, us=us, lv=lv, created_at=now) for c in code_list]
            session.add_all(code_list)
            session.commit()
            return True
        except:
            session.rollback()
            return False


def sql_update_code(code, used: int, usedtime):
    with Session() as session:
        try:
            data = {"used": used, "usedtime": usedtime}
            c = session.query(Code).filter(Code.code == code).update(data)
            if c == 0:
                return False
            session.commit()
            return True
        except Exception as e:
            print(e)
            return False


def sql_get_code(code):
    with Session() as session:
        try:
            code = session.query(Code).filter(Code.code == code).first()
            return code
        except:
            return None


def sql_count_code(tg: int = None):
    with Session() as session:
        if tg is None:
            try:
                used_count = (
                    session.query(func.count()).filter(Code.used != None).scalar()
                )
                unused_count = (
                    session.query(func.count()).filter(Code.used == None).scalar()
                )
                us_list = [30, 90, 180, 365]
                tg_mon, tg_sea, tg_half, tg_year = [
                    session.query(func.count())
                    .filter(Code.used == None)
                    .filter(Code.us == us)
                    .scalar()
                    for us in us_list
                ]
                # 公益码/普通码分类统计
                public_count = session.query(func.count()).filter(Code.used == None, Code.lv == 'e').scalar()
                normal_count = session.query(func.count()).filter(Code.used == None, Code.lv == 'b').scalar()
                return used_count, tg_mon, tg_sea, tg_half, tg_year, unused_count, public_count, normal_count
            except Exception as e:
                print(e)
                return None
        else:
            try:
                used_count = (
                    session.query(func.count())
                    .filter(Code.used != None)
                    .filter(Code.tg == tg)
                    .scalar()
                )
                unused_count = (
                    session.query(func.count())
                    .filter(Code.used == None)
                    .filter(Code.tg == tg)
                    .scalar()
                )
                us_list = [30, 90, 180, 365]
                tg_mon, tg_sea, tg_half, tg_year = [
                    session.query(func.count())
                    .filter(Code.used == None)
                    .filter(Code.us == us)
                    .filter(Code.tg == tg)
                    .scalar()
                    for us in us_list
                ]
                public_count = session.query(func.count()).filter(Code.used == None, Code.tg == tg, Code.lv == 'e').scalar()
                normal_count = session.query(func.count()).filter(Code.used == None, Code.tg == tg, Code.lv == 'b').scalar()
                return used_count, tg_mon, tg_sea, tg_half, tg_year, unused_count, public_count, normal_count
            except Exception as e:
                print(e)
                return None


def sql_count_p_code(tg_id, us):
    with Session() as session:
        try:
            if us == 0:
                p = (
                    session.query(func.count())
                    .filter(Code.used != None)
                    .filter(Code.tg == tg_id)
                    .scalar()
                )
            elif us == -1:
                p = (
                    session.query(func.count())
                    .filter(Code.used == None)
                    .filter(Code.tg == tg_id)
                    .scalar()
                )
            else:
                p = (
                    session.query(func.count())
                    .filter(Code.us == us)
                    .filter(Code.tg == tg_id)
                    .scalar()
                )
            if p == 0:
                return None, 1
            i = math.ceil(p / 30)
            a = []
            b = 1
            # 分析出页数，将检索出 分割p（总数目）的 间隔，将间隔分段，放进【】中返回
            while b <= i:
                d = (b - 1) * 30
                if us == -1:
                    result = (
                        session.query(
                            Code.tg, Code.code, Code.used, Code.usedtime, Code.us
                        )
                        .filter(Code.used == None)
                        .filter(Code.tg == tg_id)
                        .order_by(Code.us.asc())
                        .limit(30)
                        .offset(d)
                        .all()
                    )
                elif us != 0:
                    # 查询us和tg匹配的记录，按tg升序，usedtime降序排序，分页查询
                    result = (
                        session.query(Code.tg, Code.code, Code.used, Code.usedtime)
                        .filter(Code.us == us)
                        .filter(Code.tg == tg_id)
                        .filter(Code.used == None)
                        .order_by(Code.tg.asc(), Code.usedtime.desc())
                        .limit(30)
                        .offset(d)
                        .all()
                    )
                else:
                    result = (
                        session.query(
                            Code.tg, Code.code, Code.used, Code.usedtime, Code.us
                        )
                        .filter(Code.used != None)
                        .filter(Code.tg == tg_id)
                        .order_by(Code.tg.asc(), Code.usedtime.desc())
                        .limit(30)
                        .offset(d)
                        .all()
                    )
                x = ""
                e = 1 if d == 0 else d + 1
                for link in result:
                    if us == 0:
                        c = (
                            f"{e}. `"
                            + f"{link[1]}`"
                            + f"\n🎁 {link[4]}d - [{link[2]}](tg://user?id={link[0]})(__{link[3]}__)\n"
                        )
                    else:
                        c = f"{e}. `" + f"{link[1]}`\n"
                    x += c
                    e += 1
                a.append(x)
                b += 1
            # a 是数量，i是页数
            return a, i
        except Exception as e:
            # 查询失败时，打印异常信息，并返回None
            print(e)
            return None, 1


def sql_count_c_code(tg_id):
    with Session() as session:
        try:
            p = session.query(func.count()).filter(Code.tg == tg_id).scalar()
            if p == 0:
                return None, 1
            i = math.ceil(p / 5)
            a = []
            b = 1
            # 分析出页数，将检索出 分割p（总数目）的 间隔，将间隔分段，放进【】中返回
            while b <= i:
                d = (b - 1) * 5
                result = (
                    session.query(Code.tg, Code.code, Code.used, Code.usedtime, Code.us)
                    .filter(Code.tg == tg_id)
                    .order_by(Code.tg.asc(), Code.usedtime.desc())
                    .limit(5)
                    .offset(d)
                    .all()
                )
                x = ""
                e = 1 if d == 0 else d + 1
                for link in result:
                    c = (
                        f"{e}. `{link[1]}`\n"
                        f"🎁： {link[4]} 天 | 👤[{link[2]}](tg://user?id={link[2]})\n"
                        f"🌏：{link[3]}\n\n"
                    )
                    x += c
                    e += 1
                a.append(x)
                b += 1
            # a 是数量，i是页数
            return a, i
        except Exception as e:
            # 查询失败时，打印异常信息，并返回None
            print(e)
            return None, 1

def sql_delete_unused_by_days(days: list[int], user_id: int = None) -> int:
    with Session() as session:
        try:
            query = session.query(Code).filter(Code.used == None)
            if user_id is not None:
                query = query.filter(Code.tg == user_id)
            query = query.filter(Code.us.in_(days))
            result = query.delete(synchronize_session=False)
            session.commit()
            return result
        except Exception as e:
            session.rollback()
            print(f"删除注册码失败: {e}")
            return 0


def sql_delete_all_unused(user_id: int = None) -> int:
    with Session() as session:
        try:
            query = session.query(Code).filter(Code.used == None)
            if user_id is not None:
                query = query.filter(Code.tg == user_id)
            result = query.delete(synchronize_session=False)
            session.commit()
            return result
        except Exception as e:
            session.rollback()
            print(f"删除所有未使用注册码失败: {e}")
            return 0


def sql_list_codes(
    page: int = 1,
    page_size: int = 20,
    code_type: str = "all",      # all / register_b / register_e / renew
    status: str = "all",         # all / used / unused
    days: int = None,            # None=全部, 30/90/180/365
    q: str = "",                 # 模糊搜索 code 字符串
    creator_tg: int = None,      # 按创建者 TG ID 精确匹配
    used_by_tg: int = None,      # 按使用者 TG ID 精确匹配
    sort: str = "created_at",   # code / days / usedtime / created_at
    order: str = "desc",
):
    """
    分页查询注册/续期码列表（供 Admin Web 使用）
    返回 (total, items_list_of_dict)
    """
    with Session() as session:
        try:
            query = session.query(Code)

            # 按类型过滤（通过 code 字符串 LIKE + lv）
            if code_type == "register_b":
                query = query.filter(Code.code.like("%-Register_%"), Code.lv == "b")
            elif code_type == "register_e":
                query = query.filter(Code.code.like("%-Register_%"), Code.lv == "e")
            elif code_type == "renew":
                query = query.filter(Code.code.like("%-Renew_%"))
            # code_type == "all" 不过滤

            # 按使用状态过滤
            if status == "used":
                query = query.filter(Code.used != None)
            elif status == "unused":
                query = query.filter(Code.used == None)

            # 按有效天数过滤
            if days is not None:
                query = query.filter(Code.us == days)

            # 关键字搜索
            if q.strip():
                query = query.filter(Code.code.like(f"%{q.strip()}%"))

            # 创建者TG精确匹配
            if creator_tg is not None:
                query = query.filter(Code.tg == creator_tg)

            # 使用者TG精确匹配
            if used_by_tg is not None:
                query = query.filter(Code.used == used_by_tg)

            # 排序（MySQL 兼容：NULL 值排末尾，用 col IS NULL 作为首排序键）
            _sort_map = {
                "code":       Code.code,
                "days":       Code.us,
                "usedtime":   Code.usedtime,
                "created_at": Code.created_at,
            }
            sort_col = _sort_map.get(sort, Code.created_at)
            null_last = sort_col.is_(None).asc()   # NULL=0排前，非NULL=1排后→NULL last
            if order == "asc":
                query = query.order_by(null_last, sort_col.asc())
            else:
                query = query.order_by(null_last, sort_col.desc())

            total = query.count()
            rows = query.offset((page - 1) * page_size).limit(page_size).all()

            items = []
            for row in rows:
                # 根据 code 字符串判断类型
                if "Register" in row.code:
                    c_type = "register"
                elif "Renew" in row.code:
                    c_type = "renew"
                else:
                    c_type = "unknown"
                items.append({
                    "code":       row.code,
                    "type":       c_type,
                    "lv":         row.lv or "b",
                    "days":       row.us,
                    "status":     "used" if row.used else "unused",
                    "creator":    row.tg or 0,
                    "used_by":    row.used or None,
                    "used_time":  row.usedtime.strftime("%Y-%m-%d %H:%M") if row.usedtime else "",
                    "created_at": row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else "",
                })
            return total, items
        except Exception as e:
            print(f"sql_list_codes 查询失败: {e}")
            return 0, []


def sql_delete_codes_by_list(code_list: list) -> int:
    """根据 code 字符串列表批量删除（不限使用状态）"""
    with Session() as session:
        try:
            result = session.query(Code).filter(Code.code.in_(code_list)).delete(synchronize_session=False)
            session.commit()
            return result
        except Exception as e:
            session.rollback()
            print(f"批量删除注册码失败: {e}")
            return 0