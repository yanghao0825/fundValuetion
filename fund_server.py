import requests
import json
from flask import Flask, request, jsonify
import time
import math

# 禁用SSL警告
requests.packages.urllib3.disable_warnings()

app = Flask(__name__)

# 跨域配置
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

def get_jd_fund_data(fund_code):
    """
    调用京东金融接口获取基金详情（适配实际返回结构）
    :param fund_code: 6位基金代码
    :return: 解析后的基金数据
    """
    url = "https://ms.jr.jd.com/gw2/generic/life/h5/m/getFundDetailPageInfoWithNoPin"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://jr.jd.com/",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8"
    }
    params = {"fundCode": fund_code}

    try:
        response = requests.get(
            url=url,
            params=params,
            headers=headers,
            timeout=15,
            verify=False
        )
        result = response.json()
        
        # 接口返回成功判断
        if not result.get("success", False) or not result.get("resultData", {}):
            return {
                "status": "error",
                "msg": f"京东接口返回失败：{result.get('resultMsg', '未知错误')}"
            }
        
        result_data = result["resultData"]
        if result_data.get("code") != "0000":
            return {
                "status": "error",
                "msg": f"基金数据获取失败：{result_data.get('info', '接口返回异常')}"
            }
        
        datas = result_data.get("datas", {})
        header = datas.get("headerOfItem", {})
        common_attr = datas.get("commonAttributeNoPin", {})
        performance = datas.get("performanceOfItem", {})
        fund_profile = datas.get("fundProfileOfItem", {})
        fund_manager = datas.get("fundManagerOfItem", {})

        # 1. 核心估值数据
        valuation_data = {
            # 实时估值涨幅（京东接口直接返回的估算涨幅）
            "realtime_valuation_rate": float(common_attr.get("realtimeValuationOfItem", 0) or 0),
            # 最新净值（取header中的净值）
            "latest_nav": 0.0,
            "latest_nav_date": header.get("navDate", ""),
            # 日涨跌幅
            "daily_rate": 0.0
        }
        # 解析quotationsMap获取净值和日涨跌幅
        quotations = header.get("quotationsMap", [])
        for item in quotations:
            if item.get("type") == "nav":
                valuation_data["latest_nav"] = float(item.get("value", 0) or 0)
            elif item.get("type") == "dailyRate":
                valuation_data["daily_rate"] = float(item.get("value", 0) or 0)
        
        # 计算实时估算净值（最新净值 × (1 + 实时估值涨幅/100)）
        if valuation_data["latest_nav"] > 0 and valuation_data["realtime_valuation_rate"] != 0:
            valuation_data["realtime_valuation_nav"] = round(
                valuation_data["latest_nav"] * (1 + valuation_data["realtime_valuation_rate"] / 100),
                4
            )
        else:
            valuation_data["realtime_valuation_nav"] = 0.0

        # 2. 基金基础信息
        base_info = {
            "fund_code": header.get("fundCode", fund_code),
            "fund_name": header.get("fundName", "未知基金"),
            "fund_type": header.get("fundTypeName", "未知类型"),
            "established_date": fund_profile.get("establishedDate", ""),
            "fund_scale": fund_profile.get("fundScale", "0万元"),
            "fund_company": fund_profile.get("company_name", "未知公司")
        }

        # 3. 基金经理信息
        manager_list = []
        managers = fund_manager.get("managerInfoList", [])
        for m in managers:
            manager_list.append({
                "name": m.get("managerName", ""),
                "manage_scale": m.get("manageScale", ""),
                "accession_date": m.get("accessionDateDesc", "")
            })

        # 4. 历史净值数据（取最近5条）
        history_nav = []
        history_list = performance.get("historyNvOrProfitMap", {}).get("historyNvOrProfitList", [])[:5]
        for h in history_list:
            history_nav.append({
                "date": h.get("date", ""),
                "net_value": float(h.get("netValue", 0) or 0),
                "daily_profit": float(h.get("dailyProfit", 0) or 0)
            })

        return {
            "status": "success",
            "base_info": base_info,
            "valuation_data": valuation_data,
            "fund_manager": manager_list,
            "history_nav": history_nav,
            "msg": "获取基金数据成功"
        }
    except Exception as e:
        return {
            "status": "error",
            "msg": f"请求京东接口失败：{str(e)}"
        }

@app.route("/api/fund", methods=["GET"])
def query_fund():
    """前端查询接口：适配京东实际返回数据"""
    fund_code = request.args.get("code", "").strip()
    
    # 基础校验
    if not fund_code or len(fund_code) != 6 or not fund_code.isdigit():
        return jsonify({
            "code": fund_code,
            "status": "error",
            "msg": "请输入6位有效数字基金代码",
            "data": {}
        })
    
    # 调用京东接口
    jd_data = get_jd_fund_data(fund_code)
    if jd_data["status"] != "success":
        return jsonify({
            "code": fund_code,
            "status": jd_data["status"],
            "msg": jd_data["msg"],
            "data": {}
        })
    
    # 组装返回给前端的最终数据
    final_data = {
        # 基础信息
        "fund_code": jd_data["base_info"]["fund_code"],
        "fund_name": jd_data["base_info"]["fund_name"],
        "fund_type": jd_data["base_info"]["fund_type"],
        "established_date": jd_data["base_info"]["established_date"],
        "fund_company": jd_data["base_info"]["fund_company"],
        # 核心估值
        "latest_nav": jd_data["valuation_data"]["latest_nav"],  # 最新净值
        "latest_nav_date": jd_data["valuation_data"]["latest_nav_date"],  # 净值日期
        "realtime_valuation_rate": jd_data["valuation_data"]["realtime_valuation_rate"],  # 实时估值涨幅
        "realtime_valuation_nav": jd_data["valuation_data"]["realtime_valuation_nav"],  # 实时估算净值
        "daily_rate": jd_data["valuation_data"]["daily_rate"],  # 昨日涨跌幅
        # 基金经理
        "fund_manager": jd_data["fund_manager"],
        # 历史净值（最近5条）
        "history_nav": jd_data["history_nav"]
    }
    
    return jsonify({
        "code": fund_code,
        "status": "success",
        "msg": "查询成功",
        "update_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "data": final_data
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)