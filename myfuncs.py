# -*- coding: utf-8 -*-
"""
Created on Sat Apr 11 18:25:28 2020

@author: Admin
"""
import time
import datetime
import openpyxl

def 两个词组拼贴(stringset1,stringset2):
  result = []
  for i in stringset1:
    for j in stringset2:
      result.append(str(i)+'+'+str(j))
  return result

def 两个词组对比_单对单_左连接(stringset1,
                   stringset1_target_col_no,
                   stringset1_boltag_col_no,stringset1_settag_col_no,
                   stringset1_set_build_col_no,
                   stringset2,
                   stringset2_target_col_no,
                   stringset2_set_build_col_no):
  for i in stringset1:
    for j in stringset2:
      if str(i[stringset1_target_col_no]) == str(j[stringset2_target_col_no]):
        i[stringset1_boltag_col_no] = '是'
        i[stringset1_settag_col_no] = list([i[stringset1_set_build_col_no],j[stringset2_set_build_col_no]])  
  return stringset1

def 两个string年月日时分秒的时间差_string(str1,str2):
  time1 = datetime.datetime.strptime(str1, "%Y-%m-%d %H:%M:%S")
  time2 = datetime.datetime.strptime(str2, "%Y-%m-%d %H:%M:%S")
  return str(int(((time2-time1).seconds)/60+((time2-time1).days)*24*60))+'min'

def 两个string年月日时分秒的时间差_int_minute(str1,str2):
  time1 = datetime.datetime.strptime(str1, "%Y-%m-%d %H:%M:%S")
  time2 = datetime.datetime.strptime(str2, "%Y-%m-%d %H:%M:%S")
  return ((time2-time1).seconds)/60+((time2-time1).days)*24*60

def 表格读取成list(worksheet):
  row_content = []
  for row in worksheet:
    row_value = []
    for cell in row:
      row_value.append(str(cell.value))
    row_content.append(row_value)
  return row_content

def 表格读取成list_new(wb_name,ws_name):
  wb = openpyxl.load_workbook(wb_name)
  ws1 = wb[ws_name]
  nameurllist = 表格读取成list(ws1)
  return nameurllist

def 关键词比对_改变原list(被比对的list,被比对的list的具体元素序列,要改变的具体元素序列,要改成的内容,关键词组):
  for i in range(len(被比对的list)):
    for word in 关键词组:
      if word in str(被比对的list[i][被比对的list的具体元素序列]):
        被比对的list[i][要改变的具体元素序列] = 要改成的内容
  return 被比对的list

def 关键词比对_生成新list(被比对的list,被比对的list的具体元素序列,关键词组):
  row_content_1 = []
  for row in 被比对的list:
    for word in 关键词组:
      if word in row[被比对的list的具体元素序列]:
        row_content_1.append(row)
  return row_content_1

def list写入表格(worksheet,list_to_write,是否有表头_1或0,表头):
  if 是否有表头_1或0 == 0:
    num_start_write = 1
    for row in list_to_write:
      worksheet.write_row('A'+str(num_start_write),row)
      num_start_write = num_start_write + 1
  if 是否有表头_1或0 == 1:
    worksheet.write_row('A1',表头)
    num_start_write = 2
    for row in list_to_write:
      worksheet.write_row('A'+str(num_start_write),row)
      num_start_write = num_start_write + 1
      
def list合并(list1,list2):
  for row in list2:
    list1.append(row)
  return list1
  
#def list写入mysql():