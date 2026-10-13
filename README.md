# 批量抓取助手 desk research helper

## 背景 

 战略的desk research里，很大一部分是：在特定网站里，根据关键词收集网页链接，之后批量盘查、去伪存真，得出有效情报结论。 
 
 因为“特定网站里，根据关键词，收集网页链接”可以批量化，所以在2019年设计了第一版脚本(获取后再用chromedriver批量打开并获取文本做nlp分析)，2026年更新了第二版脚本（获取后结合LLM AI使用）。
 - 2019年 第一版：用chromedriver规避的方案，批量访问并获取文本，然后做nlp分析
 - 2026年 第二版：用chromedriver规避的方案，批量获取url，然后自行结合LLM AI使用 —— 简单来说就是帮忙提供一批知识边界，提升LLM使用体验
 
## 使用方法

 两个list：list1 关键词，list2 网站。安装chromedriver后，python跑。done。
