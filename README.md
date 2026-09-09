# 精英顾问陪跑系统

「90天精英顾问特训营」陪跑项目专属管理系统。按 `Role.txt` 实现五种角色的真实功能（非静态演示）：

- **系统管理员**：创建/启用/禁用账号、重置密码、系统设置、操作日志
- **代理人**：录入自有存量客户 → 系统自动生成 KYC 报告；双周提交经营动态（含新单件数/保费/FYC/转介绍数量）；查看教练反馈；查看集中辅导会总结、盘客报告；查看个人成长报告
- **教练**：查看学员经营动态，提交诊断反馈
- **项目经理**：开启经营动态周期、上传集中辅导会/盘客报告 PDF（含出勤）、上传沙龙 1&1 陪谈报告 PDF、录入代理人成长报告与结业报告（可用 AI 基于系统统计数据一键生成草稿，再人工审核发布）。孤儿单客户的分配改为线下完成，不在系统内操作
- **保司内勤**：以上全部内容的只读视图

技术选型：Python + Flask + 原生 sqlite3（不依赖 ORM，单文件数据库，便于在自建 Ubuntu 服务器上直接运行和备份）。前端为服务端渲染的 Jinja2 模板，视觉延续此前 Demo 的苹果极简风格，无需单独构建前端。

## 本地试运行

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

首次启动会自动创建 `coaching.db` 并生成：
- 系统管理员账号：`admin` / `p@ssw0rd`（**首次登录后请立即在「角色与权限管理」中重置密码**）
- 3 场集中辅导会、6 次盘客辅导、3 场沙龙的空白场次，等待项目经理录入
- 第 1 期经营动态周期（默认从今天起 14 天）

浏览器打开 `http://服务器地址:5000`。

## 部署到 Ubuntu 云服务器（生产环境）

1. **上传代码**：将本目录整体上传到服务器，例如 `/opt/coaching-platform/`。

2. **创建虚拟环境并安装依赖**
   ```bash
   cd /opt/coaching-platform
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **设置生产环境变量**（务必修改，不要使用默认值）
   ```bash
   export COACHING_SECRET_KEY="换成一个随机长字符串"
   export COACHING_ADMIN_USER="admin"        # 可选，首次建库时的管理员账号
   export COACHING_ADMIN_PASS="换一个强密码"  # 首次建库时的管理员密码
   export COACHING_DB_PATH="/opt/coaching-platform/data/coaching.db"
   export COACHING_UPLOAD_DIR="/opt/coaching-platform/data/uploads"  # 可选，不设置则默认用 COACHING_DB_PATH 同目录下的 uploads/
   export MINIMAX_API_KEY="你的 MiniMax API Key"       # 可选，不配置则「AI 生成草稿」按钮会报错提示未配置
   export MINIMAX_MODEL="MiniMax-Text-01"              # 可选，按账号可用模型调整
   ```
   成长报告/结业报告的「AI 生成草稿」功能会调用 MiniMax 的 Chat Completion 接口。传给 AI 的只有系统算好的结构化统计数字（客户分层分布、KYC 完成数、经营动态提交率、教练反馈覆盖率、出勤率、新单件数/保费/FYC/转介绍数量），不会传任何客户原始信息或经营动态/教练反馈的文字原文。AI 生成的内容始终是草稿，需要项目经理人工检查后再发布；如果对已发布内容重新生成，会自动打回草稿状态，不会静默覆盖已发布内容。

   成长报告改成五维打分（客户经营能力/KYC应用能力/活动量达成/业绩转化能力/转介绍开发），其中「活动量达成」有真实完成率可以自动算；「客户经营能力」「业绩转化能力」「转介绍开发」因为公司还没定统一的目标基准数字，系统给的是跟本期学员里最高值相比的相对分，不是对绝对目标的完成率——等定了具体目标（比如每人每期至少多少件新单），可以把 `compute_growth_score_suggestions()` 里的相对分改成目标完成率。「KYC应用能力」现状下每个客户都会自动生成报告、覆盖率恒为 100%，没有区分度，没有自动建议分，只能人工评。
   建议写入 `/etc/systemd/system/coaching-platform.service` 的 `Environment=` 中（见下）。

   集中辅导会总结/盘客报告/沙龙 1&1 陪谈报告，都是项目经理用外部小工具生成 PDF 后，在系统里手动上传（不再是系统内手打文字），上传后代理人/保司内勤点击链接即可在浏览器内直接打开查看，不会强制下载。上传文件仅限 `.pdf`，单个不超过 20MB；存储位置默认是 `COACHING_DB_PATH` 同一目录下的 `uploads/` 子目录（和 sqlite 文件一样落在同一块持久盘上），也可以用 `COACHING_UPLOAD_DIR` 单独指定一个目录。历史版本手打的文字内容字段还留在数据库里，没有 PDF 但有旧文字的场次会在页面上继续显示旧文字作为兜底，不会丢数据。

4. **用 gunicorn 启动**（不要用 `python3 app.py` 的开发服务器跑生产流量）
   ```bash
   mkdir -p data
   gunicorn -w 2 -b 127.0.0.1:8000 app:app
   ```

5. **配置 systemd 常驻服务**，新建 `/etc/systemd/system/coaching-platform.service`：
   ```ini
   [Unit]
   Description=Coaching Platform
   After=network.target

   [Service]
   WorkingDirectory=/opt/coaching-platform
   Environment=COACHING_SECRET_KEY=换成一个随机长字符串
   Environment=COACHING_DB_PATH=/opt/coaching-platform/data/coaching.db
   ExecStart=/opt/coaching-platform/venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 app:app
   Restart=always
   User=www-data

   [Install]
   WantedBy=multi-user.target
   ```
   然后：
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now coaching-platform
   ```

6. **用 Nginx 反向代理 + HTTPS**（示例，域名与证书自行替换）
   ```nginx
   server {
       listen 443 ssl;
       server_name your-domain.example.com;
       ssl_certificate     /etc/letsencrypt/live/your-domain.example.com/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/your-domain.example.com/privkey.pem;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```
   系统必须部署在 HTTPS 之后再对外使用——账号密码目前以明文表单提交，没有 HTTPS 等于在网络上裸奔。

7. **数据备份**：`coaching.db` 加上 `uploads/` 目录（各类报告 PDF）是全部数据，建议加一条 crontab 每天复制一份到别处：
   ```
   0 2 * * * cp /opt/coaching-platform/data/coaching.db /opt/coaching-platform/backup/coaching-$(date +\%F).db
   0 2 * * * rsync -a /opt/coaching-platform/data/uploads/ /opt/coaching-platform/backup/uploads-$(date +\%F)/
   ```
   系统设置里的「数据自动备份」开关目前只记录这个配置意图，实际备份任务需要按上面这条 crontab 手动启用。

## 这一版本的已知边界（诚实说明，不是隐藏的坑）

- **登录鉴权**：账号密码用 `werkzeug.security` 做加盐哈希存储，会话用 Flask 签名 Cookie；没有做限流/验证码。生产使用前建议至少加一层登录失败限流。
- **KYC 报告**：由代理人录入的字段（年龄区间、家庭结构、收入区间、已有保障等）按规则模板拼装生成，是陪跑项目内部的盘客参考，**不是核保结论**，已在报告末尾注明。
- **权限模型**：按 Role.txt 的五个角色一一对应实现。账号只有启用/禁用，没有硬删除。孤儿单客户的分配已改为线下完成，系统内不再提供录入/批量导入/编辑/删除孤儿单客户的入口；代理人自有存量客户目前也不支持编辑或删除。
- **数据规模**：sqlite 单文件数据库，20 人规模的试点完全够用；如果后续扩展到 100 人以上长期使用，建议迁移到 Postgres（代码里的 SQL 是标准语法，迁移成本不高，但目前没有做迁移脚本）。
- **没有做的**：短信/邮箱通知、移动端适配（页面是响应式的，但没有专门优化触屏交互）。这些如果需要，可以作为下一轮迭代。

## 目录结构

```
coaching_platform/
  app.py            路由与业务逻辑
  db.py             数据库连接、建表、种子数据
  auth.py           登录会话与角色权限装饰器
  kyc.py            KYC 报告生成规则
  schema.sql        表结构
  requirements.txt
  static/style.css  统一视觉样式
  templates/        各角色页面（admin/agent/coach/pm/insurer）
```
