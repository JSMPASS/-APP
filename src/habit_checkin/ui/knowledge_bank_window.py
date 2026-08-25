"""知识库页面：分类树 + 文档列表 + 知识块富文本阅读/编辑 + 思维导图关联。"""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

from habit_checkin.services.clipboard_utils import (
    bind_entry_undo,
    bind_text_paste,
    cleanup_temp_files,
    paste_clipboard_images,
)
from habit_checkin.ui.common import EmptyState, center_window, make_thumbnail, setup_styles, show_image_zoom
from habit_checkin.ui.richtext import RichTextEditor, RichTextViewer, html_to_plain
from habit_checkin.ui.theme import PALETTE, dialog_header
from habit_checkin.ui.topic_tree import TopicTreeMixin

_IMAGE_TYPES = [("图片", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"), ("所有文件", "*.*")]


class MindmapNodePicker(tk.Toplevel):
    """选择思维导图节点，用于把知识块关联到具体节点。"""

    def __init__(self, master, db):
        super().__init__(master)
        self.db = db
        self.result = None
        self.title("选择导图节点")
        self.geometry("480x560")
        self.minsize(420, 420)
        self.transient(master)
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        dialog_header(self, "选择导图节点", "选中节点后点击「关联」", title_size=14, subtitle_size=9)
        self._build()
        center_window(self)
        self.grab_set()

    def _build(self):
        P = PALETTE
        body = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            body, columns=("type",), show="tree headings", selectmode="browse",
            height=16,
        )
        self.tree.heading("#0", text="节点")
        self.tree.heading("type", text="类型")
        self.tree.column("type", width=90, anchor="w", stretch=False)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._choose())

        bottom = tk.Frame(self, bg=P["bg"], padx=14, pady=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="关联", style="Accent.TButton",
                   command=self._choose).pack(side="right", padx=8)
        self._load()

    def _load(self):
        self.tree.delete(*self.tree.get_children())
        maps = self.db.list_question_maps()
        nodes = self.db.list_question_types()
        children = {}
        for n in nodes:
            children.setdefault(n.get("parent_id"), []).append(n)
        for lst in children.values():
            lst.sort(key=lambda n: (n.get("sort_order") or 0, n["id"]))
        for m in maps:
            root = next((n for n in children.get(None, []) if n.get("map_id") == m["id"]), None)
            if not root:
                continue
            root_iid = "n{}".format(root["id"])
            self.tree.insert("", "end", iid=root_iid, text=root["name"],
                             values=("科目",), open=True)
            self._insert_children(root_iid, root["id"], children)

    def _insert_children(self, parent_iid, node_id, children):
        for child in children.get(node_id, []):
            iid = "n{}".format(child["id"])
            self.tree.insert(parent_iid, "end", iid=iid, text=child["name"],
                             values=(self._type_label(child),), open=False)
            self._insert_children(iid, child["id"], children)

    @staticmethod
    def _type_label(node):
        return {
            "subject": "科目", "category": "分类", "type": "题型",
            "free": "自由", "root": "根节点",
        }.get(node.get("node_type") or "type", "节点")

    def _choose(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一个导图节点。", parent=self)
            return
        node_id = int(sel[0][1:])
        self.result = node_id
        self.destroy()


class KnowledgeBankWindow(TopicTreeMixin, tk.Frame):
    _root_iid = "all"

    def __init__(self, master, db):
        super().__init__(master, bg=PALETTE["bg"])
        self.db = db
        self._docs = []
        self._blocks = []
        self._thumb_refs = []
        self._topic_map = {}   # iid -> topic_id
        self._doc_iid_to_id = {}
        self._block_id_to_iid = {}
        self._clipboard_tmp = []
        self._doc_empty_state = None
        self._block_empty_state = None
        setup_styles(self)
        self.configure(bg=PALETTE["bg"])
        self._build_ui()
        self._load_tree()
        self._load_docs()
        self._ctrl_v_funcid = self.winfo_toplevel().bind(
            "<Control-v>", self._on_ctrl_v, add="+")

    def destroy(self):
        try:
            self.winfo_toplevel().unbind("<Control-v>", self._ctrl_v_funcid)
        except (tk.TclError, AttributeError):
            pass
        cleanup_temp_files(self._clipboard_tmp)
        super().destroy()

    # ---------- UI ----------
    def _panel(self, master, title):
        """返回带居中标题栏的分区面板，保持三栏标题与版式一致。"""
        P = PALETTE
        panel = tk.Frame(master, bg=P["surface"], highlightthickness=1,
                         highlightbackground=P["border"])
        head = tk.Frame(panel, bg=P["heading_bg"], height=34)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text=title, bg=P["heading_bg"], fg=P["text"],
                 font=("Microsoft YaHei UI", 12, "bold"),
                 anchor="center").pack(fill="both")
        body = tk.Frame(panel, bg=P["surface"])
        body.pack(fill="both", expand=True, padx=8, pady=8)
        return panel, body

    def _section_title(self, parent, text):
        tk.Label(parent, text=text, bg=PALETTE["surface"], fg=PALETTE["text"],
                 font=("Microsoft YaHei UI", 12, "bold"),
                 anchor="center").pack(fill="x", pady=(0, 2))

    def _build_ui(self):
        P = PALETTE
        dialog_header(self, "知识库", "基本知识归档 · 富文本阅读 · 思维导图联动")
        top = tk.Frame(self, bg=P["bg"], padx=14, pady=8)
        top.pack(fill="x")
        actions = tk.Frame(top, bg=P["bg"])
        actions.pack(side="left")
        ttk.Button(actions, text="＋ 新建文档", style="Accent.TButton",
                   command=self._add_doc).pack(side="left")
        ttk.Button(actions, text="导入图片", command=self._import_images).pack(side="left", padx=8)
        ttk.Button(actions, text="编辑文档", command=self._edit_doc).pack(side="left", padx=8)
        ttk.Button(actions, text="删除文档", command=self._delete_doc).pack(side="left")

        search = tk.Frame(top, bg=P["bg"])
        search.pack(side="right")
        tk.Label(search, text="搜索：", bg=P["bg"], fg=P["text"],
                 font=("Microsoft YaHei UI", 13)).pack(side="left", padx=(16, 0))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search, textvariable=self.search_var, width=18)
        bind_text_paste(self.search_entry)
        bind_entry_undo(self.search_entry)
        self.search_entry.pack(side="left", padx=(0, 6))
        self.search_entry.bind("<Return>", lambda e: self._load_docs())
        ttk.Button(search, text="查询", command=self._load_docs).pack(side="left")

        body = tk.Frame(self, bg=P["bg"], padx=14)
        body.pack(fill="both", expand=True, pady=(0, 8))
        self.paned = ttk.Panedwindow(body, orient="horizontal")
        self.paned.pack(fill="both", expand=True)

        # 左：科目分类
        left, left_body = self._panel(self.paned, "科目分类")
        tree_frame = tk.Frame(left_body, bg=P["surface"])
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        vsb1 = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb1.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb1.pack(side="right", fill="y")
        self.tree.tag_configure("drag_target", background=PALETTE["primary_light"])
        self.tree.bind("<ButtonPress-1>", self._on_drag_press)
        self.tree.bind("<B1-Motion>", self._on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_release)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._load_docs())
        self._drag_item = None
        self._drag_active = False
        self._drag_press_time = 0.0
        self._drag_target = None
        tk.Label(left_body, text="右键管理科目 · 长按拖动调整顺序/层级",
                 bg=P["surface"], fg=P["faint"],
                 font=("Microsoft YaHei UI", 10),
                 anchor="center").pack(fill="x", pady=(4, 0))
        self.paned.add(left, weight=0)

        # 中：文档列表
        mid, mid_body = self._panel(self.paned, "文档")
        self.doc_body = mid_body
        self.doc_tree = ttk.Treeview(
            mid_body, columns=("title", "count", "images", "updated"),
            show="headings",
            selectmode="browse",
        )
        for col, txt, width, anchor in (
            ("title", "文档标题", 190, "w"),
            ("count", "知识点", 70, "center"),
            ("images", "图片", 50, "center"),
            ("updated", "更新时间", 140, "w"),
        ):
            self.doc_tree.heading(col, text=txt)
            self.doc_tree.column(col, width=width, anchor=anchor)
        vsb2 = ttk.Scrollbar(mid_body, orient="vertical", command=self.doc_tree.yview)
        self.doc_tree.configure(yscrollcommand=vsb2.set)
        self.doc_tree.pack(side="left", fill="both", expand=True)
        vsb2.pack(side="right", fill="y")
        self.doc_tree.bind("<<TreeviewSelect>>", lambda e: self._load_blocks())
        self.doc_tree.bind("<Double-1>", lambda e: self._edit_doc())
        self.paned.add(mid, weight=1)

        # 右：知识块 + 正文 + 关联
        right, right_body = self._panel(self.paned, "知识块与正文")
        toolbar = tk.Frame(right_body, bg=PALETTE["surface"])
        toolbar.pack(fill="x", pady=(0, 4))
        ttk.Button(toolbar, text="＋ 新建知识点", command=self._add_block).pack(side="left")
        ttk.Button(toolbar, text="编辑", command=self._edit_block).pack(side="left", padx=6)
        ttk.Button(toolbar, text="删除", command=self._delete_block).pack(side="left")
        ttk.Separator(right_body, orient="horizontal").pack(fill="x", pady=(0, 6))

        content = tk.Frame(right_body, bg=PALETTE["surface"])
        content.pack(fill="both", expand=True)
        list_frame = tk.Frame(content, bg=PALETTE["surface"], width=250)
        self.block_list_frame = list_frame
        list_frame.pack(side="left", fill="y")
        list_frame.pack_propagate(False)
        self._section_title(list_frame, "知识点")
        self.block_list = tk.Listbox(
            list_frame, width=24, font=("Microsoft YaHei UI", 11),
            bg=PALETTE["input"], fg=PALETTE["text"], relief="flat",
            highlightthickness=1, highlightbackground=PALETTE["border"],
            activestyle="none",
        )
        self.block_list.pack(fill="both", expand=True, pady=(4, 0))
        self.block_list.bind("<<ListboxSelect>>", lambda e: self._show_block())
        self.block_list.bind("<Double-1>", lambda e: self._edit_block())

        view_frame = tk.Frame(content, bg=PALETTE["surface"])
        view_frame.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self._section_title(view_frame, "正文预览")
        self.viewer = RichTextViewer(
            view_frame, bg=PALETTE["surface"], on_edit=self._edit_block,
            image_resolver=self.db.abs_path)
        self.viewer.pack(fill="both", expand=True, pady=(4, 0))

        link_frame = tk.Frame(right_body, bg=PALETTE["surface"])
        link_frame.pack(fill="x", pady=(8, 0))
        ttk.Separator(link_frame, orient="horizontal").pack(fill="x", pady=(0, 4))
        link_head = tk.Frame(link_frame, bg=PALETTE["surface"])
        link_head.pack(fill="x")
        tk.Label(link_head, text="思维导图关联", bg=PALETTE["surface"],
                 fg=PALETTE["text"], font=("Microsoft YaHei UI", 12, "bold"),
                 anchor="center").pack(side="left", fill="x", expand=True)
        ttk.Button(link_head, text="自动关联", command=self._auto_link_block
                   ).pack(side="right")
        ttk.Button(link_head, text="手动关联", command=self._manual_link_block
                   ).pack(side="right", padx=(0, 6))
        self.link_list = tk.Listbox(
            link_frame, height=4, font=("Microsoft YaHei UI", 10),
            bg=PALETTE["input"], fg=PALETTE["text"], relief="flat",
            highlightthickness=1, highlightbackground=PALETTE["border"],
            activestyle="none",
        )
        self.link_list.pack(fill="x", pady=(4, 0))
        ttk.Button(link_frame, text="移除选中关联", command=self._unlink_block
                   ).pack(fill="x", pady=(4, 0))
        self.paned.add(right, weight=2)

        self.paned.sashpos(0, 240)
        self.paned.sashpos(1, 560)

        self.summary = tk.Label(
            self, text="", anchor="w", padx=16, pady=5,
            bg=PALETTE["primary_light"], fg=PALETTE["primary_dark"],
            font=("Microsoft YaHei UI", 12, "bold"))
        self.summary.pack(fill="x")

    # ---------- 数据加载 ----------
    def refresh(self):
        self._load_tree()
        self._load_docs()

    def _refresh_tree(self):
        self._load_tree()
        self._load_docs()

    def _after_topic_changed(self, topic_id):
        # 增删改/停用/切换类型后，文档列表按当前选中分类重新加载。
        self._load_docs()

    def _load_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._topic_map = {}
        topics = self.db.list_topics()
        children = {}
        for t in topics:
            children.setdefault(t["parent_id"], []).append(t)
        for lst in children.values():
            lst.sort(key=lambda t: (t.get("sort_order") or 0, t["id"]))
        all_iid = "all"
        self.tree.insert("", "end", iid=all_iid, text="全部文档", open=True)
        self._topic_map[all_iid] = None

        def walk(parent_id, parent_iid):
            for t in children.get(parent_id, []):
                if t.get("kind") == "method":
                    continue
                iid = "t{}".format(t["id"])
                self.tree.insert(parent_iid, "end", iid=iid, text=t["name"], open=False)
                self._topic_map[iid] = t["id"]
                walk(t["id"], iid)

        walk(None, all_iid)
        self.tree.selection_set(all_iid)

    def _selected_topic_id(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self._topic_map.get(sel[0])

    def _load_docs(self):
        topic_id = self._selected_topic_id()
        kw = self.search_var.get().strip() or None
        self._docs = self.db.list_knowledge_docs(topic_id=topic_id, keyword=kw)
        prev = self.doc_tree.selection()
        prev_id = self._doc_iid_to_id.get(prev[0]) if prev else None
        self.doc_tree.delete(*self.doc_tree.get_children())
        self._doc_iid_to_id = {}
        for doc in self._docs:
            iid = "d{}".format(doc["id"])
            self.doc_tree.insert(
                "", "end", iid=iid,
                values=(doc["title"], doc.get("block_count") or 0,
                        doc.get("image_count") or 0,
                        self._doc_display_time(doc)),
            )
            self._doc_iid_to_id[iid] = doc["id"]
        if prev_id is not None:
            iid = "d{}".format(prev_id)
            if iid in self.doc_tree.get_children(""):
                self.doc_tree.selection_set(iid)
                self.doc_tree.see(iid)
        self.summary.configure(text="共 {} 篇知识文档".format(len(self._docs)))
        if self._docs:
            self._hide_doc_empty_state()
        else:
            self._show_doc_empty_state()
        self._load_blocks()

    def _show_doc_empty_state(self):
        self._hide_doc_empty_state()
        self._doc_empty_state = EmptyState(
            self.doc_body,
            title="还没有知识文档",
            description="上传或新建文档后，可按标题段落切分知识点，\n"
                        "并与思维导图节点自动关联。",
            action_text="＋ 新建文档",
            command=self._add_doc,
        )
        self._doc_empty_state.place_in(self.doc_body, rely=0.45)

    def _hide_doc_empty_state(self):
        if self._doc_empty_state is not None:
            try:
                self._doc_empty_state.destroy()
            except tk.TclError:
                pass
            self._doc_empty_state = None

    @staticmethod
    def _doc_display_time(doc):
        """更新时间异常（旧数据 0/空）时回退到创建时间，避免显示为 0。"""
        updated = (doc.get("updated_at") or "").strip()
        if not updated or updated in ("0", "None", "null"):
            updated = (doc.get("created_at") or "").strip()
        return (updated or "")[:16]

    def _selected_doc(self):
        sel = self.doc_tree.selection()
        if not sel:
            return None
        return self.db.get_knowledge_doc(self._doc_iid_to_id.get(sel[0]))

    def _load_blocks(self, block_id=None):
        if block_id is None:
            doc = self._selected_doc()
            if doc and getattr(self, "_pending_doc_id", None) == doc["id"]:
                block_id = getattr(self, "_pending_block_id", None)
            else:
                self._pending_doc_id = None
                self._pending_block_id = None
        doc = self._selected_doc()
        self.block_list.delete(0, "end")
        self._blocks = []
        self._block_id_to_iid = {}
        self.viewer.set_html("")
        self.link_list.delete(0, "end")
        if not doc:
            self._hide_block_empty_state()
            return
        self._blocks = self.db.list_knowledge_blocks(doc["id"])
        for i, blk in enumerate(self._blocks):
            n = len(html_to_plain(blk.get("content") or ""))
            self.block_list.insert("end", "{} · {} 字".format(blk["title"], n))
            self._block_id_to_iid[blk["id"]] = i
        if self._blocks:
            self._hide_block_empty_state()
        else:
            self._show_block_empty_state()
        if block_id is not None and block_id in self._block_id_to_iid:
            self.block_list.selection_set(self._block_id_to_iid[block_id])
            self.block_list.see(self._block_id_to_iid[block_id])
            self._show_block()

    def _show_block_empty_state(self):
        self._hide_block_empty_state()
        self._block_empty_state = EmptyState(
            self.block_list_frame,
            title="还没有知识点",
            description="点击「＋ 新建知识点」创建，正文支持加粗、字号、颜色、段落等编辑。",
            action_text="＋ 新建知识点",
            command=self._add_block,
        )
        self._block_empty_state.place_in(self.block_list_frame, rely=0.45)

    def _hide_block_empty_state(self):
        if self._block_empty_state is not None:
            try:
                self._block_empty_state.destroy()
            except tk.TclError:
                pass
            self._block_empty_state = None

    def _selected_block(self):
        sel = self.block_list.curselection()
        if not sel:
            return None
        idx = sel[0]
        if 0 <= idx < len(self._blocks):
            return self._blocks[idx]
        return None

    def _show_block(self):
        blk = self._selected_block()
        if not blk:
            self.viewer.set_html("")
            self.link_list.delete(0, "end")
            return
        self.viewer.set_html(blk.get("content") or "")
        self.link_list.delete(0, "end")
        for link in self.db.knowledge_links_for_block(blk["id"]):
            auto = "自动" if link.get("auto_link") else "手动"
            self.link_list.insert(
                "end", "{} · {} · {}（{}）".format(
                    link.get("subject_name") or "导图",
                    link.get("node_name") or "节点", auto, link["question_type_id"]))

    # ---------- 文档操作 ----------
    def _doc_title_dialog(self, title=""):
        from habit_checkin.ui.field_edit_dialog import ask_fields
        values = ask_fields(
            self, "知识文档", [
                {"key": "title", "label": "文档标题", "required": True,
                 "value": title, "placeholder": "例如：资料分析 · 增长率"},
            ],
            subtitle="文档保存后可在左侧选择所属分类",
        )
        return values["title"] if values else None

    def _add_doc(self):
        title = self._doc_title_dialog("基本知识 · {}".format(date.today().isoformat()))
        if not title:
            return
        topic_id = self._selected_topic_id()
        doc_id = self.db.add_knowledge_doc(title=title, topic_id=topic_id, source="manual")
        self._load_docs()
        self.doc_tree.selection_set("d{}".format(doc_id))
        self.doc_tree.see("d{}".format(doc_id))

    def _edit_doc(self):
        doc = self._selected_doc()
        if not doc:
            messagebox.showinfo("提示", "请先在中间列表中选择一篇文档。", parent=self)
            return
        from habit_checkin.ui.field_edit_dialog import ask_fields
        path = self.db.topic_path(doc["topic_id"]) if doc.get("topic_id") else "未分类"
        choices = [("未分类", None)] + self.db.category_paths()
        choice_labels = [label for label, _ in choices]
        current = path if path in choice_labels else "未分类"
        values = ask_fields(
            self, "编辑文档", [
                {"key": "title", "label": "文档标题", "required": True, "value": doc["title"]},
                {"key": "topic_id", "label": "所属分类", "type": "choice",
                 "choices": choice_labels, "value": current},
            ],
            subtitle="当前分类：{}；可在此改为未分类或其它具体分类".format(path or "未分类"),
        )
        if values:
            topic_id = None
            if values["topic_id"] != "未分类":
                topic_id = next(
                    (tid for label, tid in choices if label == values["topic_id"]),
                    None,
                )
            old_topic_row = None
            if doc.get("topic_id"):
                old_topic_row = self.db.conn.execute(
                    "SELECT name FROM topics WHERE id=?", (doc["topic_id"],)
                ).fetchone()
            sync_topic_name = (
                old_topic_row is not None
                and topic_id == doc.get("topic_id")
                and doc["title"] == old_topic_row["name"]
                and values["title"].strip() != doc["title"]
            )
            if sync_topic_name:
                # 该文档是科目分支对应文档，改名需要同步科目管理与思维导图
                self.db.rename_topic(doc["topic_id"], values["title"])
            else:
                self.db.update_knowledge_doc(
                    doc["id"], title=values["title"], topic_id=topic_id)
            self._load_docs()

    def _delete_doc(self):
        doc = self._selected_doc()
        if not doc:
            messagebox.showinfo("提示", "请先在中间列表中选择一篇文档。", parent=self)
            return
        topic_row = None
        if doc.get("topic_id"):
            topic_row = self.db.conn.execute(
                "SELECT id, name FROM topics WHERE id=?", (doc["topic_id"],)
            ).fetchone()
        branch_doc = topic_row is not None and doc["title"] == topic_row["name"]
        if branch_doc:
            ok = messagebox.askyesno(
                "删除联动确认",
                "「{}」是科目「{}」的对应分支文档。\n"
                "删除后将同步删除科目管理、思维导图节点、"
                "知识库分支及打卡记录和图片，不可恢复。".format(
                    doc["title"], topic_row["name"]),
                parent=self,
            )
            if ok:
                self.db.delete_topic_cascade(doc["topic_id"])
                self._load_docs()
            return
        if messagebox.askyesno(
            "删除文档", "确定删除「{}」及其全部知识点、图片和关联吗？".format(doc["title"]),
            parent=self,
        ):
            self.db.delete_knowledge_doc(doc["id"])
            self._load_docs()

    def _import_images(self):
        doc = self._selected_doc()
        if not doc:
            messagebox.showinfo("提示", "请先在中间列表中选择要导入图片的文档。", parent=self)
            return
        paths = filedialog.askopenfilenames(
            parent=self, filetypes=_IMAGE_TYPES, title="选择知识图片（可多选）")
        picked = [p for p in paths if p.lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"))]
        if not picked:
            return
        try:
            self.db.sync_knowledge_images(doc["id"], picked)
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self)
            return
        self._load_docs()
        messagebox.showinfo("导入完成", "已导入 {} 张图片到当前文档。".format(len(picked)), parent=self)

    def _paste_clipboard_images(self):
        paths, tmp = paste_clipboard_images()
        if not paths:
            return
        self._clipboard_tmp.extend(tmp)
        doc = self._selected_doc()
        if not doc:
            messagebox.showinfo("提示", "请先选择要导入图片的文档。", parent=self)
            return
        try:
            self.db.sync_knowledge_images(doc["id"], paths)
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self)
            return
        self._load_docs()
        messagebox.showinfo("导入完成", "已导入 {} 张图片到当前文档。".format(len(paths)), parent=self)

    def _on_ctrl_v(self, event):
        try:
            widget = event.widget
            if not self._is_within(widget):
                return
            cls = widget.winfo_class()
        except tk.TclError:
            return
        if cls in ("TEntry", "TCombobox", "Entry", "Text"):
            return
        self._paste_clipboard_images()

    def _is_within(self, widget):
        w = widget
        while w is not None:
            if w is self:
                return True
            try:
                w = w.master
            except tk.TclError:
                return False
        return False

    # ---------- 知识块操作 ----------
    def _add_block(self):
        doc = self._selected_doc()
        if not doc:
            messagebox.showinfo("提示", "请先在中间列表中选择一篇文档。", parent=self)
            return
        dlg = RichTextEditor(
            self, title="新建知识点",
            initial_title="", initial_html="",
            subtitle="可加粗、标红、调整字号与段落格式，正文支持插入图片",
            image_resolver=self.db.abs_path,
            image_store=self.db.store_image,
        )
        self.wait_window(dlg)
        if dlg.result:
            self.db.add_knowledge_block(
                doc["id"], dlg.result["title"], dlg.result["content"])
            self._load_docs()

    def _edit_block(self):
        blk = self._selected_block()
        if not blk:
            messagebox.showinfo("提示", "请先选择一个知识点。", parent=self)
            return
        dlg = RichTextEditor(
            self, title="编辑知识点",
            initial_title=blk["title"], initial_html=blk["content"],
            subtitle="可加粗、标红、调整字号与段落格式，正文支持插入图片",
            image_resolver=self.db.abs_path,
            image_store=self.db.store_image,
        )
        self.wait_window(dlg)
        if dlg.result:
            self.db.update_knowledge_block(
                blk["id"], dlg.result["title"], dlg.result["content"])
            doc = self._selected_doc()
            if doc:
                self._pending_doc_id = doc["id"]
                self._pending_block_id = blk["id"]
            self._load_docs()

    def _delete_block(self):
        blk = self._selected_block()
        if not blk:
            messagebox.showinfo("提示", "请先选择一个知识点。", parent=self)
            return
        if messagebox.askyesno("删除知识点", "确定删除「{}」及其导图关联吗？".format(blk["title"]), parent=self):
            self.db.delete_knowledge_block(blk["id"])
            self._load_blocks()

    # ---------- 思维导图关联 ----------
    def _auto_link_block(self):
        blk = self._selected_block()
        if not blk:
            messagebox.showinfo("提示", "请先选择一个知识点。", parent=self)
            return
        doc = self.db.get_knowledge_doc(blk["doc_id"])
        if not doc or not doc.get("topic_id"):
            messagebox.showinfo("无法自动关联", "该文档未选择科目分类，请先编辑文档设置分类。", parent=self)
            return
        added = self.db.auto_link_knowledge(doc["id"])
        self._show_block()
        messagebox.showinfo("自动关联", "已自动关联 {} 个导图节点。".format(added), parent=self)

    def _manual_link_block(self):
        blk = self._selected_block()
        if not blk:
            messagebox.showinfo("提示", "请先选择一个知识点。", parent=self)
            return
        picker = MindmapNodePicker(self, self.db)
        self.wait_window(picker)
        if picker.result is None:
            return
        try:
            self.db.link_knowledge_block(blk["id"], picker.result, auto_link=False)
        except Exception as exc:
            messagebox.showerror("关联失败", str(exc), parent=self)
            return
        self._show_block()
        messagebox.showinfo("关联完成", "知识块已关联到所选导图节点。", parent=self)

    def _unlink_block(self):
        blk = self._selected_block()
        if not blk:
            messagebox.showinfo("提示", "请先选择一个知识点。", parent=self)
            return
        sel = self.link_list.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先在下方的关联列表中选择要移除的关联。", parent=self)
            return
        links = self.db.knowledge_links_for_block(blk["id"])
        if 0 <= sel[0] < len(links):
            link = links[sel[0]]
            self.db.unlink_knowledge_block(blk["id"], link["question_type_id"])
            self._show_block()

    # ---------- 导图跳转入口 ----------
    def open_doc(self, doc_id, block_id=None):
        """思维导图跳转：定位到指定文档，并选中指定知识块。"""
        doc = self.db.get_knowledge_doc(doc_id)
        if not doc:
            return
        self.search_var.set("")
        self._load_tree()
        topic_id = doc.get("topic_id")
        if topic_id:
            path = self.db.topic_path(topic_id)
            parts = path.split(" / ") if path else []
            iid = "t{}".format(topic_id)
            if iid in self.tree.get_children(""):
                self.tree.selection_set(iid)
                self.tree.see(iid)
            else:
                # 按路径查找最近父级（科目树可能折叠）
                def find(parent_iid, path_parts):
                    for child in self.tree.get_children(parent_iid):
                        txt = self.tree.item(child, "text")
                        if txt == path_parts[0]:
                            if len(path_parts) == 1:
                                return child
                            return find(child, path_parts[1:])
                    return None

                found = find("all", parts)
                if found:
                    self.tree.selection_set(found)
                    self.tree.see(found)
        else:
            self.tree.selection_set("all")
        self._load_docs()
        iid = "d{}".format(doc_id)
        if iid in self.doc_tree.get_children(""):
            self._pending_doc_id = doc_id
            self._pending_block_id = block_id
            self.doc_tree.selection_set(iid)
            self.doc_tree.see(iid)
            self._load_blocks(block_id=block_id)
