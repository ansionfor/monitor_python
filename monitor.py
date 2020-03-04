#!/usr/bin/python3
#coding=utf-8
# Author : anson
# Toutiao : code日志
# Time : 2020-2-26

import psutil
import time
import configparser
import os
import requests
import json
import logging
import base64
import subprocess

# 配置文件
root_path = os.path.abspath(os.path.dirname(__file__)) + os.sep
config = root_path + 'config.ini'

def init_log():
    logging.basicConfig(level=10,
    format='%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s',
    filename=root_path + 'info.log')

# 初始化配置（阈值，进程，钉钉）
def init_conf():
    cf = configparser.ConfigParser()
    cf.read(config, encoding='utf-8')
    threshold = cf.items('Threshold')
    processlist = cf.items('Process')
    dingding = cf.items('Dingding')

    # 阈值配置
    threshold_map = {}
    for i in threshold:
        threshold_map[i[0]] = int(i[1])
    
    # 进程
    process_map = {}
    for i in processlist:
        process_map[i[0]] = i[1].split('#')

    # 钉钉配置
    dingding = cf.items('Dingding')
    dingding_map = {}
    for i in dingding:
        dingding_map[i[0]] = i[1]
    return [threshold_map, dingding_map, process_map]

# 实时信息
def get_alarm_info():
    # 告警频次
    cf = configparser.ConfigParser()
    cf.read(config, encoding='utf-8')
    alarm = cf.items('AlarmConf')
    alarm_map = {}
    for i in alarm:
        alarm_map[i[0]] = int(i[1])
    return alarm_map

# 监控CPU信息
def check_cpu(threshold):
    cpu_per = psutil.cpu_percent(True, True)  
    max_cpu = max(cpu_per)
    alarm = True if max_cpu > threshold else False
    return [max_cpu, alarm]
 
# 监控内存信息
def check_mem(threshold):
    mem = psutil.virtual_memory()  # 查看内存信
    mem_per = int(mem[2])
    alarm = True if mem_per > threshold else False
    return [mem_per, alarm]
 
# 监控磁盘使用率
def check_disk(threshold):
    partitions = psutil.disk_partitions(all=False)
    disk = []
    for i in partitions:
        info = psutil.disk_usage(i[1])
        disk.append(info[3])
    max_usage = max(disk)
    alarm = True if max_usage > threshold else False
    return [max_usage, alarm]

def check_process(processlist):
    pro_res = []
    is_alarm_pro = False
    
    proc_dict = {}
    for pid in psutil.pids():
        try:
            process = psutil.Process(pid)
            base64_cwd = process.cwd()
            if base64_cwd not in proc_dict:
                proc_dict[base64_cwd] = [' '.join(process.cmdline())]
            else:
                proc_dict[base64_cwd].append(' '.join(process.cmdline()))
        except psutil.NoSuchProcess:
            logging.error("no process found with pid=%s"%(pid))
    # 遍历配置的进程
    for pro in processlist:
        pro_config = processlist[pro]
        msg = "进程挂掉了!\n"
        if pro_config[0] in proc_dict.keys():
            # 遍历目录下进程
            pro_num = 0
            for dir_pro in proc_dict[pro_config[0]]:
                # 是否包含字符
                if pro_config[2] in dir_pro:
                    pro_num += 1
            if int(pro_num) < int(pro_config[3]):
                # 进程数小于配置值
                is_alarm_pro = True
                pro_res.append(pro_config)
        else:
            # 目录没有进程，报警TODO
            is_alarm_pro = True
            pro_res.append(pro_config)
    
    return [pro_res, is_alarm_pro]

# 重启进程
def restart(pro_res):
    for pro in pro_res:
        if int(pro[1]) == 1:
            # 重启
            send_alarm("正在拉起进程:" + pro[2] + '...')
            if subprocess.call(pro[4], shell=True) == 0:
                msg = "拉起进程成功,请查看确认！命令:\n" + pro[4]
                updateAlarmConf(0, 0)
            else:
                msg = "拉起进程失败,命令:\n" + pro[4]
            send_alarm(msg)

def handle(threshold, dingding, processlist, alarm):
    disk_res, is_alarm_disk = check_disk(threshold['disk'])
    mem_res, is_alarm_mem = check_mem(threshold['mem'])
    cpu_res, is_alarm_cpu = check_cpu(threshold['cpu'])
    pro_res, is_alarm_pro = check_process(processlist)
    pro_json_str = json.dumps(pro_res)

    info = ("机器：" + dingding['hostname'] +
            "\n磁盘已使用：" + str(disk_res) + '%'
            "\n内存已使用：" + str(mem_res) + '%'
            "\ncpu已使用：" + str(cpu_res) + '%')

    if is_alarm_disk or is_alarm_mem or is_alarm_cpu or is_alarm_pro:
        title = "进程挂掉了！\n" + pro_json_str + "\n" + if is_alarm_pro else "服务器资源告警！\n"
        alarm_msg = title + info + "\n请尽快处理！"
        now_time = int(time.time())

        if alarm['alarm_times'] == 0 :
            # 首次告警立马发送信息
            send_alarm(alarm_msg)
            if is_alarm_pro:
                restart(pro_res)
            updateAlarmConf(1, now_time + 60 * 3)

        elif alarm['next_alarm_time'] < int(time.time()) :
            send_alarm(alarm_msg)
            if is_alarm_pro:
                restart(pro_res)
            # 下一次告警时间 = 当前告警时间 + 告警次数 * error_interval * 60
            next_alarm_time = now_time + 60 * alarm['alarm_times'] * alarm['error_interval']
            updateAlarmConf(alarm['alarm_times'] + 1, next_alarm_time)

        else :
            # 没到下次告警时间
            return

    if not is_alarm_disk and not is_alarm_cpu and not is_alarm_mem and not is_alarm_pro:
        # 判断是否为告警恢复
        if alarm['alarm_times'] != 0 :
            alarm_msg = "服务器/进程已恢复!" + info
            send_alarm(alarm_msg)
            updateAlarmConf(0, 0)

def updateAlarmConf(alarm_times, next_alarm_time):
    cf = configparser.ConfigParser()
    cf.read(config, encoding='utf-8')
    cf.set('AlarmConf', 'alarm_times', str(alarm_times))
    cf.set('AlarmConf', 'next_alarm_time', str(next_alarm_time))
    with open(config, 'w') as f:
        cf.write(f)
 
def send_alarm(msg):
    msg = '[' + dingding['keyword'] + "]\n" + msg
    headers = {'Content-Type': 'application/json;charset=utf-8'}
    data = {
        "msgtype": "text",
        "text": {
            "content":msg
        }
    }
    logging.info(data)
    url = "https://oapi.dingtalk.com/robot/send?access_token=" + dingding['access_token']
    r = requests.post(url,data = json.dumps(data),headers=headers)
    logging.info(r.text)
  
if __name__ == '__main__':
    init_log()
    threshold, dingding, processlist = init_conf()
    while(1):
        alarm = get_alarm_info()
        handle(threshold, dingding, processlist, alarm)
        # 每隔n秒，统计一次当前计算机的使用情况。
        time.sleep(alarm['interval'])
